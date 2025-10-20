import time
import json
import os
import re

def save_checkpoint(checkpoint_file, results, case_cnt,sum_art_p, sum_art_r, sum_art_f1,sum_type_p, sum_type_r, sum_type_f1,sum_retrieval_overlap, completed_indices,skipped_cases):
    """保存断点信息"""
    checkpoint_data = {
        "results": results,
        "case_cnt": case_cnt,
        "law_articles":{
            "sum_p": sum_art_p,
            "sum_r": sum_art_r,
            "sum_f1": sum_art_f1,
        },
        "crime_type":{
            "sum_p": sum_type_p,
            "sum_r": sum_type_r,
            "sum_f1": sum_type_f1,
        },
        'sum_retrieval_overlap':sum_retrieval_overlap,
        "completed_indices": completed_indices,
        "skipped_cases": skipped_cases,
        "timestamp": time.time()
    }
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        json.dump(checkpoint_data, f, ensure_ascii=False, indent=4)
    print(f"断点已保存到：{checkpoint_file}")


def load_checkpoint(checkpoint_file):
    """加载断点信息"""
    if not os.path.exists(checkpoint_file):
        return None

    try:
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            checkpoint_data = json.load(f)
        print(f"找到断点文件，将从中断处继续执行...")
        print(f"已完成案例数：{checkpoint_data['case_cnt']}")
        print(f"已完成的案例索引： {checkpoint_data['completed_indices']}")
        return checkpoint_data
    except Exception as e:
        print(f"加载断点文件失败：{e}")
        return None


def is_case_completed(case_index, completed_indices):
    """检查案例是否已完成"""
    return case_index in completed_indices
