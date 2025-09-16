import json
from tqdm import tqdm
import requests
import os

url = "https://api.siliconflow.cn/v1/chat/completions"


def extract_case_info(case_text: str) -> dict:
    """
    从案件描述中提取 案件描述(case_description) 和 证据库。
    """

    prompt = f"""
      你是一名法律助理，你的任务是从给定的案件描述中，拆分出【案件描述】和【证据库】。

      ⚖️ 输出要求：
      1. 【案件描述】（case_description）：
        - 内容必须完全基于输入文本，只能删除涉及证据的部分，不得添加或捏造任何新信息。
        - 删除证据后可能导致语句不连贯，你需要对剩余内容进行适度调整，使其成为一段连贯、自然的文本。
        - 不需要结构化，直接输出为一段文字即可。

      2. 【证据库】（evidence pool）：
        - 将原告可能会提交的证据整理到 `plaintiff_evidence` 列表。
        - 将被告可能会提交的证据整理到 `defendant_evidence` 列表。
        - 证据条目必须严格来自输入文本，不得虚构、不得推断。

      ⚠️ 注意事项：
      - 所有信息必须来源于输入文本，不能捏造或添加新信息。
      - 输出的数据中所有信息的总和应该与输入文本一致，不得减去输入文本中的任何信息。
      - 输出请用 JSON 格式，结构如下：

      {{
        "case_description": "...",
        "plaintiff_evidence": [
          "..."
        ],
        "defendant_evidence": [
          "..."
        ]
      }}

      📄 输入文本：
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
    "Authorization": "Bearer sk-otilabqdidcgwwvrmslryzrhqmwjxxlizdzpoexjsxuxtgfx",
    "Content-Type": "application/json"
    }

    response = requests.request("POST", url, json=payload, headers=headers)

    response_data = json.loads(response.text)
    content_string = response_data['choices'][0]['message']['content']

    # 检查并移除开头的 "json\n" 或 "```json\n"，使用不同的模型，这个开头不一样，所以要做兼容性处理
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

def process_json_file(input_file: str, output_file: str):
    """
    批量处理 JSON 文件，逐条抽取 case_description 和证据库。
    """
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 检查是否存在中断文件，如果存在则加载已处理的结果和进度
    checkpoint_file = output_file + ".checkpoint"
    start_index = 0
    current_case_index = 1 # 新增：用于生成每个案例的唯一编号
    results = []

    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            checkpoint_data = json.load(f)
            start_index = checkpoint_data.get("last_processed_index", 0)
            current_case_index = checkpoint_data.get("last_case_index", 1) # 从断点加载 index
            results = checkpoint_data.get("results", [])
        print(f"✅ 从断点文件加载进度：已处理 {start_index} 个案例，当前编号从 {current_case_index} 开始。")

    for i in tqdm(range(start_index, len(data)), desc="Processing cases"):
        item = data[i]
        case_id = item.get("CaseId", "")
        fact_text = item.get("Fact", "")

        try:
            extracted = extract_case_info(fact_text)
            extracted["CaseId"] = case_id
            extracted["index"] = current_case_index # 为每个案例添加 index 编号
            current_case_index += 1 # 递增 index
            print(f'withCaseidRes:\n{extracted}')
            results.append(extracted)

            # 每处理5个案例保存一次结果和进度
            if (i + 1) % 5 == 0:
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
                with open(checkpoint_file, "w", encoding="utf-8") as f:
                    json.dump({"last_processed_index": i + 1, "last_case_index": current_case_index, "results": results}, f, ensure_ascii=False, indent=2)
                print(f"🚀 已保存 {i + 1} 个案例的断点，下一个编号为 {current_case_index}。")

        except Exception as e:
            print(f"❌ 案例 {case_id} 处理失败: {e}")
            # 保存当前已处理的结果，并中断处理
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump({"last_processed_index": i, "last_case_index": current_case_index, "results": results}, f, ensure_ascii=False, indent=2)
            print(f"🚨 处理中断，已保存 {i} 个案例的断点，下一个编号为 {current_case_index}。")
            break

    else: # 只有当循环完整执行完毕（没有被break中断）才执行
        # 最终保存所有结果
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        # 处理完成后删除断点文件
        if os.path.exists(checkpoint_file):
            os.remove(checkpoint_file)
            print("🗑️ 已删除断点文件。")


if __name__ == "__main__":
    input_path = "dataset/Judge/all.json"   # 输入文件路径
    output_path = "dataset/processed_cases.json"  # 输出文件路径
    process_json_file(input_path, output_path)
