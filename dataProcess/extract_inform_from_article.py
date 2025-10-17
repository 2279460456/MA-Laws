import json
from tqdm import tqdm
import requests
import os
from docx import Document
 

url = "https://api.siliconflow.cn/v1/chat/completions"

def extract_case_info(case_text: str) -> dict:
    """
    从案件描述中提取 案件描述(case_description) 和 证据库。
    """
    if case_text == '':
        print("该案件无输入")
        return False

    prompt = f"""
        你是一名法律文书信息提取助手。请从以下判决书文本中提取出结构化字段，并以 JSON 格式输出，不要输出中文外的语言。

        提取要求如下：
        1. 所有字段内容必须严格来源于判决书原文，不允许自行推断、生成或补充。
        2. 请保持原句完整性，不得改写原文。
        3. 仅返回一个合法的 JSON 对象，不要包含任何额外文字或注释。

        需要提取的字段及说明如下：
        {{
            "CaseId": "取自文中案号，例如'(2025)辽0911民初3216号'",
            "Fact": "提取案件事实与经过部分的内容，包括案件的起因、当事人之间的关系、争议焦点、事件经过及主要证据等。仅保留对客观事实的描述，不应包含法院推理、裁判逻辑、法律条文或条款引用等内容",
            "Reasoning": "提取法院的推理与裁判逻辑部分，包括法院对事实的认定、法律条文的适用、争议焦点的分析及判决理由等内容。避免提取案件事实或最终判决结果",
            "Judgment": "提取法院的最终裁判结果部分，包括判决主文、裁定事项或处理结果等内容，但不包括法官签名、书记员信息等",
            "Sentence": ["若涉及刑事案件的刑期信息，否则为空数组"],
            "Fine": ["罚金信息，如'罚金人民币三千元'；如无罚金则为空数组"],
            "Crime Type": ["罪名，如'危险驾驶罪'；如系民事案件则为空数组"],
            "Law Articles": {{
                "《中华人民共和国民法典》": ["条号列表使用纯阿拉伯数字，例如 ['937','939','940','944']"],
                "《中华人民共和国民事诉讼法》": ["条号列表使用纯阿拉伯数字，例如 ['147','260']"]
                —— 如果判决书中引用了其他法律，请在此对象中继续列出相应的法律名称和条号；
                —— 若无其他法律引用，则不添加额外键。
            }}
        }}

        以下是判决书全文：
        {case_text}
        """

    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "stop": ["null"],
        "temperature": 0.7,
        "top_p": 0.7,
        "top_k": 50,
        "frequency_penalty": 0.5,
        "n": 1,
        "response_format": {"type": "text"},
        "tools": [
            {
                "type": "function",
                "function": {
                    "description": "<string>",
                    "name": "<string>",
                    "parameters": {},
                    "strict": False
                }
            }
        ]
    }

    headers = {
        "Authorization": "Bearer sk-cufzubuzkfsjdlxoybyusguhruyodkztslshwiuijdzgupeu",
        "Content-Type": "application/json"
    }

    response = requests.request("POST", url, json=payload, headers=headers)

    response_data = json.loads(response.text)
    content_string = response_data['choices'][0]['message']['content']

    # 检查并移除开头的 "json\n" 或 "```json\n"，使用不同的模型，每个模型的开头不一样，所以要做兼容性处理
    if content_string.strip().startswith("```json\n"): #适用deepseek 
        content_string = content_string.strip()[len("```json\n"):].strip()
    elif content_string.strip().startswith("json\n"): #适用Qwen 
        content_string = content_string.strip()[len("json\n"):].strip()

    # 检查并移除末尾的 "```"
    if content_string.strip().endswith("```"): #Deepseek后面也有'```'，所以要除掉
        content_string = content_string.strip()[:-len("```")].strip()

    try:
        print(f'ans:\n:{content_string}')
        ans = json.loads(content_string)
    except json.JSONDecodeError as e:
        print(f"Error: 无法将 content_string 解析为 JSON: {e}")
        print(f"原始 content_string: {content_string}")
        return {}
    
    return ans

def load_docx_context(input_file: str):
    """
    从docx加载内容
    """
    try:
        doc = Document(input_file)
        full_text = []

        # 逐段读取
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                full_text.append(text)

        res = "\n".join(full_text)
        return res

    except Exception as e:
        print(f"❌ 读取失败：{input_file}\n原因：{e}")
        return ""

def process_all_cases(input_dir, output_json_path):
    """
    批量处理文件夹内所有docx文件，提取结构化法律文书信息，
    支持断点续跑（按文件名判断），并保存CaseId供后续查重。
    """
    # Step 1. 读取历史结果
    if os.path.exists(output_json_path):
        with open(output_json_path, "r", encoding="utf-8") as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                results = []
    else:
        results = []

    # Step 2. 已处理文件集合（按文件名判断，最稳妥）
    processed_files = {r.get("CaseName") for r in results if r.get("CaseName")}

    # Step 3. 收集全部docx文件
    all_files = [
        os.path.join(input_dir, f)
        for f in os.listdir(input_dir)
        if f.endswith(".docx")
    ]

    print(f"📁 共检测到 {len(all_files)} 个待处理文件。")

    # Step 4. 循环处理
    for file_path in tqdm(all_files, desc="处理中"):
        file_name = os.path.basename(file_path)

        # 跳过已处理文件（断点保护）,谨慎，不能出现案件名完全一致的案子，否则会直接跳过，一般不会出现，因为在下载文件时如果文件名一致会覆盖掉或者文件名后面加上序号
        if file_name in processed_files:
            continue

        try:
            max_retries = 3  # 最多尝试3次
            attempt = 0

            # 读取与提取
            docx_context = load_docx_context(file_path)
            res = extract_case_info(docx_context)
            
            #有时候返回的res为空,最多进行3次重新提取，如果还是没有则跳过该案例
            while('CaseId' not in res) and ( attempt < max_retries):
                attempt += 1
                print(f"⚠️ 第 {attempt} 次重试提取 CaseId ...")
                res = extract_case_info(docx_context)

            # 添加辅助信息
            res["Full Document"] = docx_context
            res["CaseName"] = file_name

            # 写入结果
            results.append(res)
            processed_files.add(file_name)

            # 实时保存进度（防止中断丢失）
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=4)

        except Exception as e:
            print(f"❌ 处理文件失败：{file_path}\n错误信息：{e}")
            continue

    print("✅ 全部处理完成，结果已保存至：", output_json_path)

if __name__ == "__main__":
    input_dir = "dataset/ministerCase/docx"
    output_json_path = "dataset/ministerCase/structured_results.json"
    process_all_cases(input_dir, output_json_path)




