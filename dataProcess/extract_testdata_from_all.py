import json
import pandas as pd

# ① 读取两个文件
with open("./dataset/Judge/all.json", "r", encoding="utf-8") as f:
    cases = json.load(f)

with open("./dataset/Judge/trainProcessed.json", "r", encoding="utf-8") as f:
    texts = json.load(f)

# ② 把 cases 转成字典形式 {CaseId: case_obj}
case_dict = {case["CaseId"]: case for case in cases}

# ③ 遍历另一个文件，根据 text_id 匹配 CaseId
matched_data = []
index = 1
for t in texts:
    text_id = t["text_id"]
    if text_id in case_dict:
        case = case_dict[text_id]
        case['case_description'] = case['Fact']
        del case['Fact']
        case['index'] = index
        index += 1
        matched_data.append(case)

# ④ 输出结果到新文件
with open("./dataset/ours/vecCases.json", "w", encoding="utf-8") as f:
    json.dump(matched_data, f, ensure_ascii=False, indent=2)

print(f"✅ 匹配完成，共找到 {len(matched_data)} 条记录")
