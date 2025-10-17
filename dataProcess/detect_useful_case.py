import os
import json

def detect_useful_case(input_path, output_path):
    """
    批量处理文件夹内所有docx文件，提取结构化法律文书信息，
    支持断点续跑（按文件名判断），并保存CaseId供后续查重。
    """
    # Step 1. 读取历史结果
    if os.path.exists(input_path):
        with open(input_path, "r", encoding="utf-8") as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                results = []
    else:
        results = []

    sumcase = 0
    newResults = []

    # Step 2. 筛选出含有 CaseId 且法律条款为阿拉伯数字的案例
    for case in results:
        # 条件 1: CaseId 存在且不为空
        if 'CaseId' not in case or not case['CaseId'].strip():
            continue

        # 条件 2: 检查 Law Articles 中是否有中文条款编号
        has_chinese_article = False
        law_articles = case.get("Law Articles", {})

        for law_name, articles in law_articles.items():
            for art in articles:
                # 判断是否包含中文“第”或“条”
                if isinstance(art, str) and ("第" in art or "条" in art):
                    has_chinese_article = True
                    # 手动进行修改
                    print(case['CaseId'])
                    break
            if has_chinese_article:
                break

        # 如果发现有中文条款编号，则跳过该案例
        if has_chinese_article:
            continue

        # 通过筛选条件，加入结果
        sumcase += 1
        newResults.append(case)

    # Step 3. 输出统计信息
    print(f"allCase: {len(results)}")
    print(f"usefulCase: {sumcase}")

    # Step 4. 保存筛选结果到新文件
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(newResults, f, ensure_ascii=False, indent=4)

    print(f"✅ 已保存 {sumcase} 个有效案例到 {output_path}")


# === 使用示例 ===
input_path = 'dataset/ministerCase/structured_results.json'
output_path = 'dataset/ministerCase/useful_cases.json'
detect_useful_case(input_path, output_path)
