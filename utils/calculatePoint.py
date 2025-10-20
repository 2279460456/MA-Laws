import re
import json

def extract_law_articles_from_text(text: str):
    try:
        # 尝试从文本中提取第一个JSON对象
        match = re.search(r"\{[\s\S]*?\}", text)
        if not match:
            return []
        ans = {}
        data = json.loads(match.group(0))
        arts = data.get("Law Articles", [])
        pre_fine = data.get("Fine",[])
        pre_sentence =  data.get("Sentence",[])
        pre_crimetype = data.get("Crime Type",[])

        # 归一化为整数列表
        pre_articles = []
        for a in arts:
            try:
                pre_articles.append(int(a))
            except Exception:
                # 尝试从字符串中提取数字
                m = re.search(r"\d+", str(a))
                if m:
                    pre_articles.append(int(m.group(0)))
        ans['pre_articles'] = pre_articles
        ans['pre_crimetype'] = pre_crimetype
        return ans
    except Exception:
        return []


def extract_law_articles_from_messages(messages):
    # 从审判长最新消息中解析结构化结果
    for msg in reversed(messages):
        if msg.get("name") == "PresidingJudge":
            content = msg.get("content", "")
            arts = extract_law_articles_from_text(content)
            if arts:
                return arts
    return {}

def compute_prf1(pred_list, true_list):
    pred_set = set(pred_list)
    true_set = set(true_list)
    tp = len(pred_set & true_set)
    pred_n = len(pred_set)
    true_n = len(true_set)
    precision = tp / pred_n if pred_n > 0 else (1.0 if true_n == 0 else 0.0)
    recall = tp / true_n if true_n > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          ) if (precision + recall) > 0 else 0.0
    return precision, recall, f1