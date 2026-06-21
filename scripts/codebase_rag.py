import os
from dotenv import load_dotenv
from langsmith import traceable
from IPython.display import display, Markdown

from langchain_openai import ChatOpenAI
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate


load_dotenv('.env')

API_KEY = os.environ['GITHUB_API_KEY']
ENDPOINT= os.environ['GITHUB_ENDPOINT']
MODEL_ID= os.environ['GITHUB_MODEL_ID']
OLLAMA_ENDPOINT= os.environ['OLLAMA_ENDPOINT']
OLLAMA_EMBEDDING_MODEL= os.environ['OLLAMA_EMBEDDING_MODEL']
CHROMA_PATH = "./codebase_db" 

embeddings = OllamaEmbeddings(
    model= OLLAMA_EMBEDDING_MODEL, 
    base_url= OLLAMA_ENDPOINT
)

vectorstore = Chroma(
    persist_directory=CHROMA_PATH,
    embedding_function=embeddings
)
retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

llm = ChatOpenAI(
    model=MODEL_ID, 
    base_url=ENDPOINT, 
    api_key=API_KEY, 
    temperature=0
)

system_prompt = (
    "You are an expert software engineer analyzing a codebase. "
    "Use the following pieces of retrieved codebase context to answer the user's question. "
    "If you don't know the answer, just say that you don't know. "
    "Include code snippets in your answer if helpful."
    "\n\n"
    "{context}"
)

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{input}"),
])

@traceable(name="1. Retrieve Context", run_type="retriever")
def retrieve_documents(query: str):
    """Fetches documents from ChromaDB."""
    return retriever.invoke(query)


@traceable(name="2. Format Documents")
def format_docs(docs) -> str:
    """Extracts text from LangChain Document objects and joins them."""
    return "\n\n".join(doc.page_content for doc in docs)


@traceable(name="3. Generate Answer", run_type="llm")
def generate_answer(query: str, context: str) -> str:
    """Compiles the prompt and calls Groq."""
    messages = prompt.invoke({"input": query, "context": context})
    
    response = llm.invoke(messages)
    return response.content


@traceable(name="Ancient Egypt RAG Pipeline")
def AncientEgyptRAG(query: str) -> dict:
    """The main orchestrator function."""
    
    docs = retrieve_documents(query)
    
    context_string = format_docs(docs)
    
    answer = generate_answer(query, context_string)
    
    return {
        "answer": answer,
        "source_documents": docs
    }


if __name__ == "__main__": 
    question = "How does the authentication flow work between auth.py and login.html?"
    response = AncientEgyptRAG(question)
            
    answer = response["answer"]

    display(Markdown(answer))