import os
import requests
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.utils import embedding_functions
from sentence_transformers import SentenceTransformer

# Constants
PDF_PATH = "/workspaces/explorellm/Vivek_B_Resume_DE2.pdf"
DB_PATH = "./chroma_db"
COLLECTION_NAME = "rag_collection"
MODEL_NAME = "mistralai/Mistral-7B-Instruct-v0.1"  # Together.ai model

# Get API key from environment variable
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
if not TOGETHER_API_KEY:
    raise ValueError("Please set the TOGETHER_API_KEY environment variable")

# 1. Read PDF and extract text
def pdf_reader(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None

# 2. Split text into chunks
def textsplitter(text):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len
    )
    documents = text_splitter.create_documents([text])
    return [doc.page_content for doc in documents]

# 3. Initialize ChromaDB with dummy embeddings
def init_vector_db(db_path=DB_PATH, collection_name=COLLECTION_NAME):
    client = chromadb.PersistentClient(path=db_path)

    # Load real embedding model
    model = SentenceTransformer("all-MiniLM-L6-v2")

    class SBERTEmbeddingFunction:
        def __call__(self, input: list[str]) -> list[list[float]]:
            if isinstance(input, str):  # Optional, defensive
                input = [input]
            return model.encode(input).tolist()

        def name(self):
            return "sbert-mini"

    embedding_function = SBERTEmbeddingFunction()

    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_function
    )
    return collection
# 4. Add documents (chunks) to ChromaDB
def add_documents_to_collection(collection, chunks):
    if collection.count() == 0:
        ids = [f"pdf_chunk_{i}" for i in range(len(chunks))]
        print(f"Adding {len(chunks)} chunks to the vector DB...")
        collection.add(documents=chunks, ids=ids)
    else:
        print("Collection already populated.")

# 5. Query vector DB for relevant chunks
def query_collection(collection, query, n_results=2):
    results = collection.query(query_texts=[query], n_results=n_results)
    return results['documents'][0]

# 6. Call Together.ai API to generate answer
def generate_answer_with_together(prompt):
    url = "https://api.together.xyz/v1/completions"
    headers = {
        "Authorization": f"Bearer {TOGETHER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "max_tokens": 512,
        "temperature": 0.2,
        "stop": ["\n\n"]
    }
    response = requests.post(url, json=data, headers=headers)
    if response.status_code == 200:
        return response.json()["choices"][0]["text"].strip()
    else:
        print("Error:", response.status_code, response.text)
        return None

def simple_planner(query):
    query_lower = query.lower()
    if "summarize" in query_lower:
        return "summarize"
    elif "hr" in query_lower and "action" in query_lower:
        return "extract_hr"
    else:
        return "general"
# Tool 1: Summarizer
def tool_summarize(text):
    prompt = f"Summarize the following text:\n\n{text}\n\nSummary:"
    return generate_answer_with_together(prompt)

# Tool 2: Extract HR-related action items
def tool_extract_hr_tasks(text):
    prompt = f"From the following text, extract action items relevant to the HR department:\n\n{text}\n\nItems:"
    return generate_answer_with_together(prompt)

# Tool 3: Answer general question
def tool_answer_question(text, question):
    prompt = f"""
Using the following context, answer the question. If the answer is not in the context,
say you don't know.

Context:
{text}

Question: {question}

Answer:
"""
    return generate_answer_with_together(prompt)


# Main function
def main():
    print("Reading PDF...")
    text = pdf_reader(PDF_PATH)
    if not text:
        print("No text extracted. Exiting.")
        return

    print("Splitting text into chunks...")
    chunks = textsplitter(text)
    
    print("Initializing vector database...")
    collection = init_vector_db()
    
    print("Adding chunks to vector database...")
    add_documents_to_collection(collection, chunks)
    
    query = input("\nEnter your question: ")
    print(f"\nSearching for relevant chunks for query: '{query}'")
    retrieved_chunks = query_collection(collection, query, n_results=2)
    
    print("\nRetrieved Chunks:")
    for i, chunk in enumerate(retrieved_chunks):
        print(f"\nChunk {i+1}:\n{chunk}")

#     context = "\n".join(retrieved_chunks)
#     prompt = f"""
# Using the following context, answer the question. If the answer is not in the context,
# say you don't know.

# Context:
# {context}

# Question: {query}

# Answer:
# """

#     print("\nGenerating answer from Together.ai LLM...")
#     answer = generate_answer_with_together(prompt)

    context = "\n".join(retrieved_chunks)
    action = simple_planner(query)

    print(f"\n[Agent Plan]: Detected intent → {action}")

    if action == "summarize":
        answer = tool_summarize(context)
    elif action == "extract_hr":
        answer = tool_extract_hr_tasks(context)
    else:
        answer = tool_answer_question(context, query)

    print("\n--- Agentic Answer ---")
    print(answer if answer else "Failed to generate answer.")
    if answer:
        print("\n--- Generated Answer ---")
        print(answer)
    else:
        print("Failed to generate answer.")

if __name__ == "__main__":
    main()