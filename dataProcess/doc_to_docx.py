import os
from win32com import client as wc
from docx import Document
from tqdm import tqdm
import time

def doc2docx(origin_path, goal_path):
    for i in tqdm(os.listdir(origin_path), desc="Converting .doc to .docx"):
        if i.endswith('.doc') and not i.startswith('~$'):
            try:
                doc_path = os.path.join(origin_path, i)
                rename = os.path.splitext(i)[0]
                save_path = os.path.join(goal_path, rename + '.docx')

                # 每次新建一个 Word 实例
                word = wc.Dispatch("Word.Application")
                word.Visible = False
                word.DisplayAlerts = 0  # 不显示警告框

                doc = word.Documents.Open(doc_path)
                doc.SaveAs(save_path, 12)  # 12 -> docx
                doc.Close()
                word.Quit()

                time.sleep(0.2)  # 给 COM 一点休息时间（避免 RPC 崩溃）

            except Exception as e:
                print(f"❌ 转换失败 {i}：{e}")
                try:
                    word.Quit()  # 确保关闭Word实例
                except:
                    pass
                continue


origin_path = 'D:\PostGrad\ScienceResearch\experiment\MA-Laws\dataset\ministerCase\doc'
goal_path =  'D:\PostGrad\ScienceResearch\experiment\MA-Laws\dataset\ministerCase\docx'
doc2docx(origin_path,goal_path)
