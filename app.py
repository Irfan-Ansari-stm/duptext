from flask import Flask, request, render_template, send_file, flash, redirect, url_for
import os
import PyPDF2
import re
from collections import defaultdict
from werkzeug.utils import secure_filename
import tempfile
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(pdf_path):
    """Extract text from PDF file page by page"""
    pages_text = {}
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page_num, page in enumerate(pdf_reader.pages, 1):
                text = page.extract_text()
                pages_text[page_num] = text
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {str(e)}")
    return pages_text

def clean_sentence(sentence):
    """Clean and normalize sentence for comparison"""
    sentence = re.sub(r'\s+', ' ', sentence.strip())
    sentence = re.sub(r'\b\d+\b', '', sentence)  # Remove standalone numbers
    sentence = re.sub(r'[^\w\s.,!?;:\-()]', ' ', sentence)  # Replace special chars with space
    sentence = re.sub(r'\s+', ' ', sentence.strip())  # Clean up extra spaces
    return sentence.lower()

def extract_sentences(text):
    """Extract sentences from text with multiple approaches"""
    sentences = []
    
    sent_split = re.split(r'[.!?]+', text)
    for sentence in sent_split:
        cleaned = clean_sentence(sentence)
        if len(cleaned.split()) >= 3 and len(cleaned.strip()) > 10:
            sentences.append(cleaned)
    
    phrase_split = re.split(r'[.!?;,\n\r]+', text)
    for phrase in phrase_split:
        cleaned = clean_sentence(phrase)
        if len(cleaned.split()) >= 5 and len(cleaned.strip()) > 20:
            sentences.append(cleaned)
    
    lines = text.split('\n')
    for line in lines:
        cleaned = clean_sentence(line)
        if len(cleaned.split()) >= 2 and len(cleaned.strip()) > 8:
            sentences.append(cleaned)
    
    unique_sentences = []
    seen = set()
    for sentence in sentences:
        if sentence not in seen and sentence.strip():
            seen.add(sentence)
            unique_sentences.append(sentence)
    
    return unique_sentences

def similarity_check(s1, s2, threshold=0.8):
    """Check if two sentences are similar enough to be considered duplicates"""
    s1_words = set(s1.split())
    s2_words = set(s2.split())
    
    if not s1_words or not s2_words:
        return False
    
    intersection = s1_words.intersection(s2_words)
    union = s1_words.union(s2_words)
    
    jaccard_similarity = len(intersection) / len(union) if union else 0
    return jaccard_similarity >= threshold

def find_duplicates(pdf_files):
    """Find duplicate sentences across all PDF files"""
    sentence_locations = defaultdict(list)
    all_sentences = []
    
    for pdf_file in pdf_files:
        filename = pdf_file['filename']
        pages_text = extract_text_from_pdf(pdf_file['path'])
        
        for page_num, text in pages_text.items():
            if not text.strip():
                continue
                
            sentences = extract_sentences(text)
            
            for sentence in sentences:
                if sentence and len(sentence.strip()) > 5:  
                    location_info = {
                        'filename': filename,
                        'page': page_num,
                        'sentence': sentence
                    }
                    sentence_locations[sentence].append(location_info)
                    all_sentences.append(location_info)
    
    duplicates = {}
    processed_sentences = set()
    
    for sentence, locations in sentence_locations.items():
        if sentence in processed_sentences:
            continue
            
        if len(locations) > 1:
            duplicates[sentence] = locations
            processed_sentences.add(sentence)
            continue
        
        similar_locations = [locations[0]]  # Start with the original
        
        for other_sentence, other_locations in sentence_locations.items():
            if (other_sentence != sentence and 
                other_sentence not in processed_sentences and
                similarity_check(sentence, other_sentence, threshold=0.7)):
                
                similar_locations.extend(other_locations)
                processed_sentences.add(other_sentence)
        
        if len(similar_locations) > 1:
            duplicates[sentence] = similar_locations
            processed_sentences.add(sentence)
    
    return duplicates

def generate_report(duplicates):
    """Generate text report of duplicate sentences"""
    report_lines = []
    report_lines.append("DUPLICATE SENTENCES REPORT")
    report_lines.append("=" * 50)
    report_lines.append(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Total duplicate sentences found: {len(duplicates)}")
    report_lines.append("")
    
    if not duplicates:
        report_lines.append("No duplicate sentences found across the uploaded PDF files.")
        report_lines.append("")
        report_lines.append("TROUBLESHOOTING TIPS:")
        report_lines.append("- Make sure your PDFs contain readable text (not just images)")
        report_lines.append("- Try PDFs with some common content or repeated phrases")
        report_lines.append("- The app looks for sentences with 3+ words")
        report_lines.append("- Both exact matches and similar sentences (70%+ similarity) are detected")
    else:
        for i, (sentence, locations) in enumerate(duplicates.items(), 1):
            report_lines.append(f"{i}. DUPLICATE SENTENCE:")
            report_lines.append(f"   \"{sentence[:100]}{'...' if len(sentence) > 100 else ''}\"")
            report_lines.append(f"   Found in {len(locations)} locations:")
            
            file_groups = defaultdict(list)
            for location in locations:
                file_groups[location['filename']].append(location['page'])
            
            for filename, pages in file_groups.items():
                pages_str = ', '.join(map(str, sorted(set(pages))))
                report_lines.append(f"   - File: {filename}, Pages: {pages_str}")
            
            report_lines.append("")
    
    return "\n".join(report_lines)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'files' not in request.files:
        flash('No files selected')
        return redirect(url_for('index'))
    
    files = request.files.getlist('files')
    
    if not files or all(file.filename == '' for file in files):
        flash('No files selected')
        return redirect(url_for('index'))
    
    valid_files = []
    for file in files:
        if file and allowed_file(file.filename):
            valid_files.append(file)
        else:
            flash(f'Invalid file type: {file.filename}. Only PDF files are allowed.')
    
    if not valid_files:
        return redirect(url_for('index'))
    
    temp_files = []
    try:
        for file in valid_files:
            filename = secure_filename(file.filename)
            temp_path = os.path.join(tempfile.gettempdir(), filename)
            file.save(temp_path)
            temp_files.append({
                'filename': filename,
                'path': temp_path
            })
        
        duplicates = find_duplicates(temp_files)
        
        print(f"Debug: Processing {len(temp_files)} files")
        for temp_file in temp_files:
            pages_text = extract_text_from_pdf(temp_file['path'])
            total_sentences = 0
            for page_num, text in pages_text.items():
                sentences = extract_sentences(text)
                total_sentences += len(sentences)
                print(f"File: {temp_file['filename']}, Page {page_num}: {len(sentences)} sentences")
            print(f"Total sentences in {temp_file['filename']}: {total_sentences}")
        
        report_content = generate_report(duplicates)
        
        report_filename = f"duplicate_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        report_path = os.path.join(tempfile.gettempdir(), report_filename)
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        flash(f'Analysis complete! Found {len(duplicates)} duplicate sentences.')
        return send_file(report_path, as_attachment=True, download_name=report_filename)
        
    except Exception as e:
        flash(f'Error processing files: {str(e)}')
        return redirect(url_for('index'))
    
    finally:
        for temp_file in temp_files:
            try:
                os.remove(temp_file['path'])
            except:
                pass

if __name__ == '__main__':
    app.run(debug=True)

