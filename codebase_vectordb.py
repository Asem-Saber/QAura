import os
from dotenv import load_dotenv
from langchain_community.document_loaders.generic import GenericLoader
from langchain_community.document_loaders.parsers import LanguageParser
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

load_dotenv() 
OLLAMA_ENDPOINT= os.environ['OLLAMA_ENDPOINT']
OLLAMA_EMBEDDING_MODEL= os.environ['OLLAMA_EMBEDDING_MODEL']

# load documents 
py_loader = GenericLoader.from_filesystem(
    "./demo_app",
    glob="**/*",
    suffixes=[".py"],
    parser=LanguageParser(
        language=Language.PYTHON, 
        parser_threshold=10 
    ) 
)
py_docs = py_loader.load()

html_loader = DirectoryLoader('./demo_app', glob="**/*.html", loader_cls=TextLoader)
html_docs = html_loader.load()


py_splitter = RecursiveCharacterTextSplitter.from_language(
    language=Language.PYTHON, chunk_size=1500, chunk_overlap=150
)
py_splits = py_splitter.split_documents(py_docs)

html_splitter = RecursiveCharacterTextSplitter.from_language(
    language=Language.HTML, chunk_size=1500, chunk_overlap=150
)
html_splits = html_splitter.split_documents(html_docs)

all_splits = py_splits + html_splits
print(f"Loaded {len(all_splits)} chunks from the codebase.")

ollama_embeddings = OllamaEmbeddings(
    model= OLLAMA_EMBEDDING_MODEL, 
    base_url= OLLAMA_ENDPOINT
)

vectorstore = Chroma.from_documents(documents=all_splits, embedding=ollama_embeddings, persist_directory="./codebase_db")