import json
import os
import hashlib
from google import genai
from google.genai import types
import base64
import argparse
import datetime

class WorkflowConfig:
    # 按功能分类的模型配置
    MODELS = {
        'extraction': 'gemini-2.0-flash-lite-001',  # 信息提取
        'collection': 'gemini-2.0-flash-001',       # 信息搜集
        'analysis': 'gemini-2.0-flash-001',         # 信息分析
        'summarization': 'gemini-2.0-flash-lite-001' # 信息总结
    }

    # 按功能分类的生成配置
    GENERATE_CONFIGS = {
        'extraction': types.GenerateContentConfig(
            temperature=0.3,
            top_p=0.5,
            max_output_tokens=120,
            response_modalities=["TEXT"],
            response_mime_type="application/json"
        ),
        'collection': types.GenerateContentConfig(
            temperature=1,
            top_p=0.95,
            max_output_tokens=2400,
            response_modalities=["TEXT"],
            tools=[types.Tool(google_search=types.GoogleSearch())]
        ),
        'analysis': types.GenerateContentConfig(
            temperature=1,
            top_p=0.95,
            max_output_tokens=2400,
            response_modalities=["TEXT"]
        ),
        'summarization': types.GenerateContentConfig(
            temperature=0.5,
            top_p=0.5,
            max_output_tokens=120,
            response_modalities=["TEXT"],
            response_mime_type="application/json"
        )
    }

    # 输出文件配置
    OUTPUT_FILES = {
        'extraction': 'output_1.json',
        'collection': 'output_2',
        'analysis': 'output_3',
        'summarization': 'output_4.json',
        'invalid': 'invalid'  # 新增无效文件标记
    }
    
    # 按功能分类的prompt模板
    PROMPT_TEMPLATES = {
        'extract_image': '''Now is {time} extract the name, address and date from the image return in json format as follows:
{"name": "name of the owner of this file, without social titles", "country": "ISO 3166 code of Country or administrative region", "address": "other part of address", "date":"date when this file issue","is_valid": "Issue date within three months, true/false"}
Tips:
- use "null" to fill a field when you feel it is hard to extract this part of information like:{ "name":"null"}
- You can introduce the country of this file from the text
- keep the original language of the information from file
- Please arrange English addresses from smallest to largest
- Don't keep line breaks in "address"''',
        'extract_pdf': '''Now is {time} extract the name, address and date from the document return in json format as follows:
{"name": "name of the owner of this file, without social titles", "country": "ISO 3166 code of Country or administrative region", "address": "other part of address", "date":"date when this file issue","is_valid": "Issue date within three months, true/false"}
Tips:
- use "null" to fill a field when you feel it is hard to extract this part of information like:{ "name":"null"}
- You can introduce the country of this file from the text
- keep the original language of the information from file
- Please arrange English addresses from smallest to largest
- Don't keep line breaks in "address"''',

        'collection': '''Search for information about the community or building mentioned 
in the address<address>{address}</address>, including the specific location of the community or building, 
whether it is a residential area, how many buildings there are, which block exist (pay attention to regional customs,and list all the blocks may exist), 
how many floors each building has, and how many units are on each floor. Please gather this information step by step.''',
        
        'analysis': '''<information>{previous_output}</information>base on the information I given, please check this address<address>{address}</address> step by step:
- given address must perfect match the address from information
- If the building is a residential area?
- if the block exist?
    -- block 4 block 13 may not exist
- if the floor exist?
- if the unit exist?''',
        
        'summarization': '''<analysis>{previous_output}</analysis>
Based on the analysis above, please provide a JSON format summary that includes:
- address_match: whether the address matches (true/false)
- is_residential: whether it is a residential area (true/false)
- block_exists: whether the block exists (true/false)
- floor_exists: whether the floor exists (true/false)
- unit_exists: whether the unit exists (true/false)'''
    }

def pdf_to_base64(file_path):
    with open(file_path, 'rb') as pdf_file:
        pdf_data = pdf_file.read()
        base64_encoded = base64.b64encode(pdf_data).decode('utf-8')
    return base64_encoded

def image_to_base64(image_path):
    with open(image_path, 'rb') as image_file:
        image_data = image_file.read()
        base64_encoded = base64.b64encode(image_data).decode('utf-8')
    return base64_encoded

# 主流程函数
def main(file_path, client):
    # 获取文件名(不带扩展名)作为哈希对象
    file_name = os.path.splitext(os.path.basename(file_path))[0]
    hash_object = hashlib.md5(file_name.encode())
    folder_name = hash_object.hexdigest()[:8]
    
    base_dir = os.path.join(os.getcwd(), folder_name)
    os.makedirs(base_dir, exist_ok=True)
    
    # 提取文件信息并保存到文件夹
    extracted_data = extract_data(client, file_path, base_dir)

    if extracted_data is None:
        return
    
    # 检查is_valid字段是否为false
    is_valid = extracted_data.get('is_valid')
    if is_valid is False or (isinstance(is_valid, str) and is_valid.lower() == 'false'):
        invalid_path = os.path.join(base_dir, WorkflowConfig.OUTPUT_FILES.get('invalid', 'invalid'))
        with open(invalid_path, 'w', encoding='utf-8') as f:
            f.write("date")
        return
    
    # 验证并获取地址
    if not extracted_data.get('address'):
        error_path = os.path.join(base_dir, 'error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write("address not found")
        return
    
    address = extracted_data['address']
    
    # 继续原有流程
    info = collect_information(client, address, base_dir)
    if info is None:
        return
    
    analysis = analyze_information(client, info, address, base_dir)
    if analysis is None:
        return
    
    summary = summarize_analysis(client, analysis, base_dir)
    if summary is None:
        return
    
    print("总结结果:", summary)

# 信息处理函数
def collect_information(client, address, base_dir):
    model = WorkflowConfig.MODELS['collection']
    config = WorkflowConfig.GENERATE_CONFIGS['collection']
    prompt = WorkflowConfig.PROMPT_TEMPLATES['collection'].format(address=address)
    
    msg = types.Part.from_text(text=prompt)
    contents = [types.Content(role="user", parts=[msg])]
    
    try:
        response = client.models.generate_content(model=model, contents=contents, config=config)
        text = response.text
    except Exception as e:
        error_path = os.path.join(base_dir, 'error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write(f"generate content failed: {str(e)}")
        return None

    with open(os.path.join(base_dir, WorkflowConfig.OUTPUT_FILES['collection']), 'w', encoding='utf-8') as f:
        f.write(text)
    
    search_results_dir = os.path.join(base_dir, 'search_results')
    os.makedirs(search_results_dir, exist_ok=True)
    
    # 添加边界条件检查
    if not hasattr(response, 'candidates') or len(response.candidates) == 0:
        return text
        
    first_candidate = response.candidates[0]
    if hasattr(first_candidate, 'grounding_metadata') and \
       hasattr(first_candidate.grounding_metadata, 'grounding_chunks'):
        chunks = first_candidate.grounding_metadata.grounding_chunks
        for i, chunk in enumerate(chunks):
            if hasattr(chunk, 'web'):
                title = getattr(chunk.web, 'title', 'No title available')
                uri = getattr(chunk.web, 'uri', 'No URI available')
                
                with open(os.path.join(search_results_dir, f'source_{i+1}'), 'w', encoding='utf-8') as f:
                    f.write(f"Title: {title}\nURI: {uri}\n")
    
    return text

def analyze_information(client, previous_output, address, base_dir):
    model = WorkflowConfig.MODELS['analysis']
    config = WorkflowConfig.GENERATE_CONFIGS['analysis']
    prompt = WorkflowConfig.PROMPT_TEMPLATES['analysis'].format(
        previous_output=previous_output,
        address=address
    )
    msg = types.Part.from_text(text=prompt)
    contents = [types.Content(role="user", parts=[msg])]
    
    try:
        response = client.models.generate_content(model=model, contents=contents, config=config)
        text = response.text
    except Exception as e:
        error_path = os.path.join(base_dir, 'error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write(f"analysis failed: {str(e)}")
        return None

    with open(os.path.join(base_dir, WorkflowConfig.OUTPUT_FILES['analysis']), 'w', encoding='utf-8') as f:
        f.write(text)
    return text

def summarize_analysis(client, previous_output, base_dir):
    model = WorkflowConfig.MODELS['summarization']
    config = WorkflowConfig.GENERATE_CONFIGS['summarization']
    prompt = WorkflowConfig.PROMPT_TEMPLATES['summarization'].format(
        previous_output=previous_output
    )
    msg = types.Part.from_text(text=prompt)
    contents = [types.Content(role="user", parts=[msg])]
    
    try:
        response = client.models.generate_content(model=model, contents=contents, config=config)
        text = response.text
    except Exception as e:
        error_path = os.path.join(base_dir, 'error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write(f"summary failed: {str(e)}")
        return None

    try:
        json_output = json.loads(text)
        with open(os.path.join(base_dir, WorkflowConfig.OUTPUT_FILES['summarization']), 'w', encoding='utf-8') as f:
            json.dump(json_output, f, ensure_ascii=False, indent=2)
        return json_output
    except json.JSONDecodeError as e:
        error_path = os.path.join(base_dir, 'error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write(f"JSON解析错误: {str(e)}\n原始响应:\n{text}")
        return None

def extract_image(client, file_path, image_type):
    model = WorkflowConfig.MODELS['extraction']
    config = WorkflowConfig.GENERATE_CONFIGS['extraction']
    current_time = datetime.datetime.now().strftime("%Y-%m-%d")  # 获取当前日期
    prompt = WorkflowConfig.PROMPT_TEMPLATES['extract_image'].format(time=current_time)  # 格式化prompt
    
    msg_image = types.Part.from_bytes(
        data=image_to_base64(file_path),
        mime_type="image/"+image_type
    )
    
    msg_text = types.Part.from_text(text=prompt)
    
    contents = [
        types.Content(
            role="user",
            parts=[msg_image, msg_text]
        )
    ]
    
    try:
        response = client.models.generate_content(model=model, contents=contents, config=config)
        return response.text
    except Exception:
        error_dir = os.path.dirname(file_path)
        error_path = os.path.join(error_dir, 'error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write("generate content fail")
        return None

def extract_document(client, file_path):
    model = WorkflowConfig.MODELS['extraction']
    config = WorkflowConfig.GENERATE_CONFIGS['extraction']
    current_time = datetime.datetime.now().strftime("%Y-%m-%d")  # 获取当前日期
    prompt = WorkflowConfig.PROMPT_TEMPLATES['extract_pdf'].format(time=current_time)  # 格式化prompt
    
    msg_document = types.Part.from_bytes(
        data=pdf_to_base64(file_path),
        mime_type="application/pdf"
    )

    msg_text = types.Part.from_text(text=prompt)
    
    contents = [
        types.Content(
            role="user",
            parts=[msg_document, msg_text]
        )
    ]
    
    try:
        response = client.models.generate_content(model=model, contents=contents, config=config)
        return response.text
    except Exception:
        error_dir = os.path.dirname(file_path)
        error_path = os.path.join(error_dir, 'error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write("generate content fail")
        return None

# 文件提取函数
def extract_data(client, file_path, base_dir):
    file_extension = os.path.splitext(file_path)[1].lower()
    text = None  # 显式初始化为None
    
    if file_extension not in ['.pdf', '.jpg', '.jpeg', '.png']:
        error_path = os.path.join(base_dir, 'error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write("unsupported file type")
        return None
    
    if file_extension == '.pdf':
        text = extract_document(client, file_path)
    elif file_extension in ['.jpg', '.jpeg', '.png']:
        image_type = 'jpeg' if file_extension == '.jpg' else file_extension[1:]
        text = extract_image(client, file_path, image_type)
    else:
        # 这个分支理论上不会执行，但添加它以消除警告
        return None
    
    if text is None:
        error_path = os.path.join(base_dir, 'error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write("content extraction failed")
        return None
    
    try:
        json_output = json.loads(text)
        output_path = os.path.join(base_dir, 'output_1.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(json_output, f, ensure_ascii=False, indent=2)
        return json_output
    except json.JSONDecodeError as e:
        error_path = os.path.join(base_dir, 'output_1.error')
        with open(error_path, 'w', encoding='utf-8') as f:
            f.write(f"JSON解析错误: {str(e)}\n原始响应:\n{text}")
        return None

if __name__ == "__main__":
    # 设置命令行参数解析
    parser = argparse.ArgumentParser(description='Process documents and images')
    parser.add_argument('-p', '--path', type=str, help='Path to the PDF/image file')
    args = parser.parse_args()
    
    client = genai.Client(
        vertexai=True,
        project="nifty-saga-443304-j8",
        location="global",
    )
    
    if args.path:
        # 如果提供了文件路径，则处理该文件
        main(args.path, client)
    else:
        # 如果没有提供路径，保持原有行为
        address = ""
        main(address, client)