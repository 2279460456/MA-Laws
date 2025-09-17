import json


def convert_to_json_array(input_file, output_file):
    #将原始非json格式的文件转化为合法的、可以遍历的文件
    
    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read().strip()

    # 每个对象之间用 '}\n{' 分隔，改成 '},\n{' 再加上 []
    content = "[" + content.replace("}\n{", "},\n{") + "]"

    data = json.loads(content)  # 确认是否能解析
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 使用方法
convert_to_json_array("dataset/judge/train.json", "dataset/judge/trainProcessed.json")
