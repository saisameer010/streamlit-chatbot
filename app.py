import openai
import streamlit as st
import os
import sqlite3
import hashlib
from dotenv import load_dotenv
from datetime import datetime
import boto3
import json

# Load environment variables from .env file
load_dotenv()

# Set up your OpenAI API key here
openai.api_key = os.getenv("OPENAI_API_KEY")

# Initialize SQLite database
conn = sqlite3.connect('users.db', check_same_thread=False)
c = conn.cursor()

# Create tables if they don't exist
c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS chat_history (username TEXT, prompt TEXT, response TEXT, timestamp DATETIME)''')
conn.commit()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username, password):
    hashed_password = hash_password(password)
    c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hashed_password))
    return c.fetchone() is not None

def add_user(username, password):
    hashed_password = hash_password(password)
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def add_chat_history(username, prompt, response):
    timestamp = datetime.now()
    c.execute("INSERT INTO chat_history (username, prompt, response, timestamp) VALUES (?, ?, ?, ?)", (username, prompt, response, timestamp))
    conn.commit()
    # Delete oldest entry if history exceeds 20 items
    c.execute("DELETE FROM chat_history WHERE username = ? AND timestamp = (SELECT MIN(timestamp) FROM chat_history WHERE username = ?) AND (SELECT COUNT(*) FROM chat_history WHERE username = ?) > 20", (username, username, username))
    conn.commit()

def get_chat_history(username):
    c.execute("SELECT prompt, response, timestamp FROM chat_history WHERE username = ? ORDER BY timestamp DESC LIMIT 20", (username,))
    return c.fetchall()

def generate_response(prompt):
    try:
        print(f"Generating response for prompt: {prompt}")
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=150
        )
        print(f"Response received: {response}")
        return response.choices[0].text.strip()
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        return f"Error: {str(e)}"

def get_data_from_s3(username):
    s3 = boto3.client('s3')
    bucket_name = os.getenv("S3_BUCKET_NAME")
    user_folder = f"{username}/"
    local_folder = f"data/{username}/"
    os.makedirs(local_folder, exist_ok=True)

    try:
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=user_folder)
        if 'Contents' in response:
            for obj in response['Contents']:
                key = obj['Key']
                if key.endswith('.json'):
                    local_path = os.path.join(local_folder, os.path.basename(key))
                    s3.download_file(bucket_name, key, local_path)
                    print(f"Downloaded {key} to {local_path}")
    except Exception as e:
        print(f"Error downloading files from S3: {str(e)}")

def main():
    st.set_page_config(page_title="OpenAI Chat", page_icon=":robot_face:", layout="wide")
    st.title("OpenAI API with Streamlit")
    st.markdown("This is a simple Streamlit app that interacts with OpenAI's API.")

    # User Authentication
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None

    menu = ["Login", "Sign Up"]
    if not st.session_state.logged_in:
        choice = st.sidebar.selectbox("Menu", menu)

        if choice == "Sign Up":
            st.subheader("Create a New Account")
            new_user = st.text_input("Username")
            new_password = st.text_input("Password", type='password')
            if st.button("Sign Up"):
                if add_user(new_user, new_password):
                    st.success("Account created successfully! Please log in.")
                else:
                    st.error("Username already exists. Please choose a different one.")

        elif choice == "Login":
            st.subheader("Login to Your Account")
            username = st.sidebar.text_input("Username")
            password = st.sidebar.text_input("Password", type='password')
            if st.sidebar.button("Login"):
                if authenticate_user(username, password):
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    get_data_from_s3(st.session_state.username)
                else:
                    st.error("Invalid username or password.")
    if st.session_state.logged_in:
        st.success(f"Welcome {st.session_state.username}!")
        
        st.subheader("Chat History")
        chat_history = get_chat_history(st.session_state.username)
        for entry in reversed(chat_history[:5]):
            st.markdown(f"""**Prompt:** {entry[0]}  
                         **Response:** {entry[1]}  
                         *Timestamp:* {entry[2]}""")
        prompt = st.text_area("Enter your prompt:", "Tell me a joke about AI.")
        print(f"User entered prompt: {prompt}")

        if st.button("Generate Response"):
            print("Generate Response button clicked")
            if prompt.strip():
                with st.spinner("Generating response..."):
                    # Load JSON files to provide context to GPT
                    user_data_folder = f"data/{st.session_state.username}/"
                    context = ""
                    if os.path.exists(user_data_folder):
                        for filename in os.listdir(user_data_folder):
                            if filename.endswith('.json'):
                                with open(os.path.join(user_data_folder, filename), 'r') as file:
                                    context += f"\n\n FILE {filename} :\n"
                                    context += file + "\n"
                                    context += " END FILE  \n"
                    full_prompt = context + "\n" + prompt
                    response = generate_response(full_prompt)
                    st.success("Done!")
                    st.text_area("Response from OpenAI:", value=response, height=200)
                    print(f"Generated response: {response}")
                    add_chat_history(st.session_state.username, prompt, response)
            else:
                st.warning("Please enter a prompt before generating a response.")
                print("Warning: No prompt entered")

        # Display chat history
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.sidebar.success("Logged out successfully.")

if __name__ == "__main__":
    import sys
    main()
