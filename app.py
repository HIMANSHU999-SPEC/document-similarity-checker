# app.py
# A local web application to check for similarity between multiple PDF and DOCX documents.
# Version 6.3 - Corrected the logic for minimum matching block size.
#
# Author: Himanshu Chadha
# Company: London Academy for Applied Technology
#
# To Run This App:
# 1. Make sure you have Python installed.
# 2. Open your terminal or command prompt.
# 3. Install the required libraries by running this command:
#    pip install streamlit scikit-learn pymupdf pandas plotly python-docx
# 4. Save this code as a file named `app.py`.
# 5. In your terminal, navigate to the folder where you saved the file.
# 6. Run the command:
#    streamlit run app.py
import streamlit as st
import fitz  # PyMuPDF library for PDFs
import docx  # python-docx library for Word docs
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import pandas as pd
import plotly.express as px
import itertools
from collections import defaultdict
from difflib import SequenceMatcher

# --- Core Logic Functions ---

def extract_text(file_object):
    """Extracts text from an uploaded file (PDF or DOCX)."""
    try:
        if file_object.type == "application/pdf":
            pdf_document = fitz.open(stream=file_object.read(), filetype="pdf")
            text = "".join(page.get_text() for page in pdf_document)
            pdf_document.close()
            return text
        elif file_object.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            document = docx.Document(file_object)
            text = "\n".join(para.text for para in document.paragraphs)
            return text
        else:
            st.warning(f"Unsupported file type: {file_object.name}. Only PDF and DOCX are supported.")
            return ""
    except Exception as e:
        st.error(f"Error reading file '{file_object.name}': {e}")
        return ""

def calculate_similarity(cv_texts):
    """Calculates the cosine similarity matrix using the TF-IDF method."""
    vectorizer = TfidfVectorizer(stop_words='english', strip_accents='unicode', lowercase=True)
    tfidf_matrix = vectorizer.fit_transform(cv_texts)
    return cosine_similarity(tfidf_matrix)

def get_matching_blocks(text1, text2, min_size):
    """Uses difflib to find and return matching blocks of text."""
    matcher = SequenceMatcher(None, text1.split(), text2.split(), autojunk=False)
    matching_blocks = []
    for block in matcher.get_matching_blocks():
        # --- FIX: Changed from > to >= to include blocks of exactly min_size ---
        if block.size >= min_size:
            block_text1 = " ".join(text1.split()[block.a:block.a + block.size])
            block_text2 = " ".join(text2.split()[block.b:block.b + block.size])
            matching_blocks.append((block_text1, block_text2))
    return matching_blocks

# --- Streamlit User Interface ---

st.set_page_config(layout="wide", page_title="Document Similarity Checker | LAAT")

# Initialize session state to store results
if 'results' not in st.session_state:
    st.session_state.results = None

with st.sidebar:
    st.image("https://laat.ac.uk/assets/img/laat-logo.jpg", width=200)
    st.title("London Academy for Applied Technology")
    st.header("⚙️ Controls")
    uploaded_files = st.file_uploader("Upload Documents (PDF or DOCX)", type=["pdf", "docx"], accept_multiple_files=True)
    similarity_threshold = st.slider("Similarity Threshold", 0.0, 1.0, 0.80, 0.05, help="Flags pairs with a score above this value.")
    
    min_block_size = st.number_input("Minimum Matching Block Size (words)", min_value=3, max_value=50, value=10, help="Sets the minimum word count for a text block to be considered a match in the in-depth view.")

    MAX_FILE_SIZE_MB = 4
    MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

    if st.button("Analyze Documents", type="primary", use_container_width=True):
        if uploaded_files and len(uploaded_files) >= 2:
            oversized = [f.name for f in uploaded_files if f.size > MAX_FILE_SIZE_BYTES]
            if oversized:
                for name in oversized:
                    st.error(f"❌ '{name}' exceeds the {MAX_FILE_SIZE_MB} MB file size limit and cannot be processed.")
                st.session_state.results = None
            else:
                with st.spinner("Analyzing... Please wait."):
                    doc_data = []
                    for i, file in enumerate(uploaded_files):
                        text = extract_text(file)
                        if text:
                            doc_data.append({"id": f"Doc #{i+1}", "filename": file.name, "text": text})
                
                if len(doc_data) >= 2:
                    doc_texts = [item['text'] for item in doc_data]
                    doc_ids = [item['id'] for item in doc_data]
                    similarity_matrix = calculate_similarity(doc_texts)
                    
                    similar_pairs = []
                    for i in range(len(similarity_matrix)):
                        for j in range(i + 1, len(similarity_matrix)):
                            if similarity_matrix[i][j] >= similarity_threshold:
                                similar_pairs.append({
                                    "doc1_index": i, "doc2_index": j,
                                    "doc1_id": doc_ids[i], "doc2_id": doc_ids[j],
                                    "score": similarity_matrix[i][j]
                                })
                    
                    st.session_state.results = {
                        "doc_data": doc_data,
                        "doc_texts": doc_texts,
                        "doc_ids": doc_ids,
                        "similarity_matrix": similarity_matrix,
                        "similar_pairs": similar_pairs,
                        "threshold": similarity_threshold,
                        "min_block_size": min_block_size
                    }
                else:
                    st.session_state.results = None
        else:
            st.warning("⚠️ Please upload at least two documents.")
            st.session_state.results = None

    st.markdown("---")
    st.info("Created by: **Himanshu Chadha**")

st.title("📄 Document Similarity Checker")
st.markdown("This tool analyzes a batch of documents to identify textual similarities and shows the exact matching text.")

if st.session_state.results:
    results = st.session_state.results
    doc_data = results['doc_data']
    doc_texts = results['doc_texts']
    doc_ids = results['doc_ids']
    similarity_matrix = results['similarity_matrix']
    similar_pairs = results['similar_pairs']
    threshold = results['threshold']
    min_block_size_used = results.get('min_block_size', 10) 

    st.header("📊 Analysis Results")

    st.subheader("✅ Uploaded Documents Reference Key")
    reference_df = pd.DataFrame(doc_data)[['id', 'filename']].rename(columns={'id': 'Assigned ID', 'filename': 'Original Filename'})
    st.dataframe(reference_df, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Docs Analyzed", f"{len(doc_data)}")
    col2.metric("Similar Pairs Found", f"{len(similar_pairs)}")
    col3.metric("Total Comparisons", f"{len(list(itertools.combinations(doc_ids, 2)))}")

    if similar_pairs:
        st.subheader("🔬 In-Depth Comparison")
        st.markdown("Select a pair from the dropdown below to see the exact matching text blocks.")
        
        pair_options = [f"Compare {p['doc1_id']} and {p['doc2_id']} ({p['score']:.0%}) " for p in similar_pairs]
        selected_pair_str = st.selectbox("Choose a similar pair to inspect:", options=pair_options, key="pair_selector")

        if selected_pair_str:
            selected_index = pair_options.index(selected_pair_str)
            selected_pair_data = similar_pairs[selected_index]
            
            doc1_text = doc_texts[selected_pair_data['doc1_index']]
            doc2_text = doc_texts[selected_pair_data['doc2_index']]

            matching_blocks = get_matching_blocks(doc1_text, doc2_text, min_block_size_used)
            
            st.markdown(f"---")
            col_left, col_right = st.columns(2)
            col_left.subheader(f"Matches in {selected_pair_data['doc1_id']}")
            col_right.subheader(f"Matches in {selected_pair_data['doc2_id']}")

            if matching_blocks:
                for block1, block2 in matching_blocks:
                    col_left.markdown(f"> ...`{block1}`...")
                    col_right.markdown(f"> ...`{block2}`...")
            else:
                st.info(f"No matching blocks of text found with {min_block_size_used} or more words.")
        
        st.markdown(f"---")
        
        st.subheader("🎯 Similarity Hotspots")
        hotspots = defaultdict(list)
        for p in similar_pairs:
            hotspots[p['doc1_id']].append(p['doc2_id'])
            hotspots[p['doc2_id']].append(p['doc1_id'])
        hotspot_data = [{"Problematic Doc ID": doc_id, "Times Flagged": len(matches), "Similar To": ", ".join(matches)} for doc_id, matches in hotspots.items()]
        hotspot_df = pd.DataFrame(hotspot_data).sort_values(by="Times Flagged", ascending=False)
        st.dataframe(hotspot_df, use_container_width=True)

        st.subheader(f"Detailed List of Similar Pairs (Threshold > {threshold:.0%})")
        results_df_data = [{"Doc ID 1": p['doc1_id'], "Filename 1": doc_data[p['doc1_index']]['filename'], "Doc ID 2": p['doc2_id'], "Filename 2": doc_data[p['doc2_index']]['filename'], "Similarity Score": f"{p['score']:.2%}"} for p in similar_pairs]
        st.dataframe(pd.DataFrame(results_df_data), use_container_width=True)

    else:
        st.success(f"✅ No pairs found with a similarity score above {threshold:.0%}.")

    st.subheader("Visual Similarity Matrix")
    fig = px.imshow(similarity_matrix, x=doc_ids, y=doc_ids, color_continuous_scale='Blues', text_auto=".2f", labels=dict(color="Similarity"))
    fig.update_xaxes(side="top")
    fig.update_layout(title_text='Document-to-Document Similarity Scores', title_x=0.5)
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("Upload your PDF and DOCX files and click 'Analyze Documents' to begin.")





