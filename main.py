from autogen import (AssistantAgent, GroupChat,
                     GroupChatManager, config_list_from_json)
from utils import (findCase, getPrompt,
                   extract_law_articles_from_messages, compute_prf1, save_checkpoint, load_checkpoint, is_case_completed)
import time
import json
import os
import re

# === 全局配置 ===
OUT_ROUNDS = 10  #必须为偶数
In_ROUNDS = 4
config_list = config_list_from_json(env_or_file="configs/config_list.json")

MODEL_CONFIG = {
    "config_list": config_list,
    "cache_seed": None,
    "temperature": 1,
    "timeout": 300,
}

# 该类负责判断外部群聊何时结束
class CourtTerminator:
    def __init__(self, defendantTeamDelegate, plaintiffTeamDelegate, PresidingJudge, plaintiff_evidence=[], defendant_evidence=[]):
        self.defendantTeamDelegate = defendantTeamDelegate
        self.plaintiffTeamDelegate = plaintiffTeamDelegate
        self.PresidingJudge = PresidingJudge
        self.plaintiff_spoken = False
        self.defendant_spoken = False
        self.plaintiff_supplement_done = False
        self.defendant_supplement_done = False
        self.plaintiff_evidence = plaintiff_evidence
        self.defendant_evidence = defendant_evidence

    def delay_bind(self, manager):
        self.manager = manager

    def __call__(self, msg):
        name = msg.get("name")
        print('此处判断该函数是否执行')
        # if name == "PlaintiffTeamDelegate":
        #     self.plaintiff_spoken = True
        # if name == "DefendantTeamDelegate":
        #     self.defendant_spoken = True
        # # 当原告已发言 且 还没补充证据 → 插入补充环节
        # if self.plaintiff_spoken and not self.plaintiff_supplement_done and self.plaintiff_evidence:
        #     self.plaintiff_supplement_done = True
        #     print("🔎 进入证据补充环节：允许原告补充一次证据")
        #     # 后续对request_reply设置为True或False进行效果测试
        #     self.plaintiffTeamDelegate.send(
        #         message=f'原告补充证据集和：{self.plaintiff_evidence}', recipient=self.manager, request_reply=True)
        #     return False  # 不结束
        # # 当被告已发言 且 还没补充证据 → 插入补充环节
        # if self.defendant_spoken and not self.defendant_supplement_done and self.defendant_evidence:
        #     self.defendant_supplement_done = True
        #     print("🔎 进入证据补充环节：允许被告补充一次证据")
        #     # 后续对request_reply设置为True或False进行效果测试
        #     self.defendantTeamDelegate.send(
        #         message=f'被告补充证据集和：{self.defendant_evidence}', recipient=self.manager, request_reply=True)
        #     return False  # 不结束
        
        # 只允许 PresidingJudge 说“庭审结束”时中断
        if name == "PresidingJudge" and any(kw in msg.get("content", "") for kw in ["庭审结束", "本次审理到此结束", "宣判完毕"]):
            print('限定测试文字')
            return True
        return False

# 原告团队发言人
class PlaintiffTeamDelegate(AssistantAgent):
    def __init__(self, *args, **kwargs):
        self.internal_manager = kwargs.pop("internal_manager")
        self.case_description = kwargs.pop("case_description")
        self.all_internal_debates = kwargs.pop(
            "all_internal_debates")  # 添加此行以接收列表
        filtered_kwargs = {k: v for k, v in kwargs.items()}
        super().__init__(*args, **filtered_kwargs)

    def delay_bind(self, manager):
        self.manager = manager

    def generate_reply(self, messages=None, sender=None, exclude=None, **kwargs):
        if not messages:
            messages = self.manager.groupchat.messages

        last_defand_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "PlaintiffTeamDelegate":
                last_defand_msg = msg.get("content", "")
                break

        print(f"\n--- PlaintiffTeamDelegate 收到法庭消息，转发给内部团队讨论 ---")
        internal_message = (
            f"案件描述: {self.case_description}\n"
            f"被告方的最近一次发言内容：{last_defand_msg}\n"
            "请团队成员仔细分析法庭消息。"
        )

        plaintiff_internal_chat_result = self.initiate_chat(
            self.internal_manager,
            message=internal_message,
        )

        # Extract the internal debate history, skipping the initial prompt from PlaintiffTeamDelegate
        internal_debate_history = self.internal_manager.groupchat.messages[:] if len(
            self.internal_manager.groupchat.messages) > 1 else []
        self.all_internal_debates.append(
            internal_debate_history)  # 将本次内部讨论历史追加到列表中
        team_reply = "原告团队内部未能达成一致意见。"  # Default reply

        if internal_debate_history:
            # 优先寻找首席律师的最后一条消息
            lead_counsel_replies = [msg for msg in internal_debate_history if msg.get(
                'name') == "PlaintiffLeadCounsel"]
            if lead_counsel_replies:
                team_reply = lead_counsel_replies[-1]['content']
            else:
                # 如果没有首席律师的回复，则使用内部讨论中的最后一条消息
                team_reply = internal_debate_history[-1]['content']

        print(f"\n--- PlaintiffTeamDelegate 将内部团队讨论结果作为发言 ---")
        return {
            "content": team_reply,
        }

# 创建被告团队发言人
class DefendantTeamDelegate(AssistantAgent):
    def __init__(self, *args, **kwargs):
        self.internal_manager = kwargs.pop("internal_manager")
        self.case_description = kwargs.pop("case_description")
        self.all_internal_debates = kwargs.pop(
            "all_internal_debates")  # 添加此行以接收列表
        filtered_kwargs = {k: v for k, v in kwargs.items()}
        super().__init__(*args, **filtered_kwargs)

    def delay_bind(self, manager):
        self.manager = manager

    def generate_reply(self, messages=None, sender=None, exclude=None, **kwargs):
        if not messages:
            messages = self.manager.groupchat.messages

        last_plaintiff_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "PlaintiffTeamDelegate":
                last_plaintiff_msg = msg.get("content", "")
                break

        print(f"\n--- DefendantTeamDelegate 收到法庭消息，转发给内部团队讨论 ---")
        internal_message = (
            f"案件描述: {self.case_description}\n"
            f"原告方的最近一次发言内容：{last_plaintiff_msg}\n"
            "请团队成员仔细分析法庭消息。"
        )

        # Initiate an internal chat with the defendant team
        defendant_internal_chat_result = self.initiate_chat(
            self.internal_manager,
            message=internal_message,
        )

        # Extract the internal debate history, skipping the initial prompt from DefendantTeamDelegate
        internal_debate_history = self.internal_manager.groupchat.messages[:] if len(
            self.internal_manager.groupchat.messages) >= 1 else []
        self.all_internal_debates.append(
            internal_debate_history)  # 将本次内部讨论历史追加到列表中
        team_reply = "被告团队内部未能达成一致意见。"  # Default reply

        if internal_debate_history:
            # 优先寻找首席律师的最后一条消息
            lead_counsel_replies = [msg for msg in internal_debate_history if msg.get(
                'name') == "DefendantLeadCounsel"]
            if lead_counsel_replies:
                team_reply = lead_counsel_replies[-1]['content']
            else:
                # 如果没有首席律师的回复，则使用内部讨论中的最后一条消息
                team_reply = internal_debate_history[-1]['content']

        print(f"\n--- DefendantTeamDelegate 将内部团队讨论结果作为发言 ---")
        return {
            "content": team_reply,
        }

# 模拟法庭
class CourtAgents:
    def __init__(self):
        # 审判长
        self.PresidingJudge = AssistantAgent(
            name="PresidingJudge",
            llm_config=MODEL_CONFIG,
            system_message=getPrompt('PresidingJudge')
        )
        # 原告代表
        self.PlaintiffLeadCounsel = AssistantAgent(
            name="PlaintiffLeadCounsel",
            llm_config=MODEL_CONFIG,
            system_message=getPrompt('PlaintiffLeadCounsel')
        )
        # 原告证据专家
        self.PlaintiffEvidenceSpecialist = AssistantAgent(
            name="PlaintiffEvidenceSpecialist",
            llm_config=MODEL_CONFIG,
            system_message=getPrompt('PlaintiffEvidenceSpecialist')
        )
        # 原告法律研究员
        self.PlaintiffLegalResearcher = AssistantAgent(
            name="PlaintiffLegalResearcher",
            llm_config=MODEL_CONFIG,
            system_message=getPrompt('PlaintiffLegalResearcher')
        )
        # 被告代表
        self.DefendantLeadCounsel = AssistantAgent(
            name="DefendantLeadCounsel",
            llm_config=MODEL_CONFIG,
            system_message=getPrompt('DefendantLeadCounsel'),
        )
        # 被告证据专家
        self.DefendantEvidenceSpecialist = AssistantAgent(
            name="DefendantEvidenceSpecialist",
            llm_config=MODEL_CONFIG,
            system_message=getPrompt('DefendantEvidenceSpecialist'),
        )
        # 被告法律研究员
        self.DefendantLegalResearcher = AssistantAgent(
            name="DefendantLegalResearcher",
            llm_config=MODEL_CONFIG,
            system_message=getPrompt('DefendantLegalResearcher'),
        )
    # 自定义发言选择逻辑
    def custom_speaker_selector(self,last_speaker, groupchat):

        round_idx = len(groupchat.messages)  # 当前发言计数（每条消息算一次发言）

        # 还没到最后一轮：原告与被告轮流发言
        if round_idx < OUT_ROUNDS - 1:
            if last_speaker.name == 'PresidingJudge':
                return self.plaintiffTeamDelegate
            elif last_speaker.name == "PlaintiffTeamDelegate":
                return self.defendantTeamDelegate
            else:
                return self.plaintiffTeamDelegate

        # 最后一轮让法官发言
        else:
            return self.PresidingJudge

    def run_simulation(self, case_data: dict,  out_dir: str):
        """
        运行一个完整的法庭模拟案例。
        param case_data: 包含案件所有信息的字典，应包含 'index', 'CaseId', 'case_description, "defendant_evidence","plaintiff_evidence"'
        """

        case_index = case_data['index']
        CaseId = case_data['CaseId']
        case_description = case_data['case_description']
        # plaintiff_evidence = case_data['plaintiff_evidence']
        # defendant_evidence = case_data['defendant_evidence']
        case_true_articles = case['Law Articles']
        case_true_type = case['Crime Type']
        case_true_sentence = case['Sentence']
        case_true_fine = case['Fine']

        print(f"\n===== 正在运行模拟案例 {case_index}: {CaseId} =====\n")

        # 用于收集所有内部讨论历史的列表
        all_plaintiff_internal_debates = []
        all_defendant_internal_debates = []

        # 原告团队内部群聊
        plaintiff_internal_agents = [self.PlaintiffEvidenceSpecialist,
                                     self.PlaintiffLegalResearcher, self.PlaintiffLeadCounsel]
        plaintiff_internal_groupchat = GroupChat(
            agents=plaintiff_internal_agents,
            messages=[],
            max_round=In_ROUNDS,  # 内部讨论轮次可以少一些
            speaker_selection_method="round_robin",
            allow_repeat_speaker=False,  # 内部讨论不应该重复发言人
            select_speaker_auto_verbose=False  # 设置为True会展示为什么选择这个人
        )
        plaintiff_internal_manager = GroupChatManager(
            groupchat=plaintiff_internal_groupchat,
            llm_config=MODEL_CONFIG
        )
        # 原告团队代表
        self.plaintiffTeamDelegate = PlaintiffTeamDelegate(
            name="PlaintiffTeamDelegate",
            llm_config=MODEL_CONFIG,
            system_message=getPrompt('PlaintiffTeamDelegate'),
            internal_manager=plaintiff_internal_manager,
            case_description=case_description,
            all_internal_debates=all_plaintiff_internal_debates  # 传递列表
        )
        
        # 被告团队内部群聊
        defendant_internal_agents = [self.DefendantEvidenceSpecialist,
                                     self.DefendantLegalResearcher, self.DefendantLeadCounsel]
        defendant_internal_groupchat = GroupChat(
            agents=defendant_internal_agents,
            messages=[],
            max_round=In_ROUNDS,
            speaker_selection_method="round_robin",
            allow_repeat_speaker=False,  # 内部讨论不应该重复发言人
            select_speaker_auto_verbose=False  # 设置为True会展示为什么选择这个人
        )
        defendant_internal_manager = GroupChatManager(
            groupchat=defendant_internal_groupchat,
            llm_config=MODEL_CONFIG
        )
        # 被告团队代表
        self.defendantTeamDelegate = DefendantTeamDelegate(
            name="DefendantTeamDelegate",
            llm_config=MODEL_CONFIG,
            system_message=getPrompt('DefendantTeamDelegate'),
            internal_manager=defendant_internal_manager,
            case_description=case_description,
            all_internal_debates=all_defendant_internal_debates  # 传递列表
        )
        
        # 实例化判断外部对话何时终止的类
        terminator = CourtTerminator(defendantTeamDelegate=self.defendantTeamDelegate, plaintiffTeamDelegate=self.plaintiffTeamDelegate,
                                     PresidingJudge=self.PresidingJudge)

        # 构建外部对话群聊
        debate_agents = [self.PresidingJudge,
                         self.plaintiffTeamDelegate, self.defendantTeamDelegate]
        groupchat = GroupChat(
            agents=debate_agents,
            messages=[],
            max_round=OUT_ROUNDS,
            speaker_selection_method=self.custom_speaker_selector,
            allow_repeat_speaker=False,
            select_speaker_auto_verbose=False
        )
        manager = GroupChatManager(
            groupchat=groupchat,
            llm_config=MODEL_CONFIG,
            is_termination_msg=terminator
        )

        # 延迟注入manager
        terminator.delay_bind(manager)
        self.plaintiffTeamDelegate.delay_bind(manager)
        self.defendantTeamDelegate.delay_bind(manager)
    
        # 检索相似案例
        try:
            retrieved_laws = findCase(case_description)
        except Exception as e:
            print(f"[警告] 相似案例检索失败：{e}")
            retrieved_laws = []

        # === 阶段一：庭审辩论 ===
        time.sleep(3)
        initial_message = (
            f"法庭辩论现在开始。\n【案件编号】: {case_index}\n【案件ID】: {CaseId}\n"
            f"【案情简介】: {case_description}\n\n"
            "我作为审判长将主导本次辩论。原告团队，请提出你的开场陈述，陈述你方的诉求和证据。"
            f"经检索相似案例，参考以往判决结果，本案可援引的相关刑法条文包括：{retrieved_laws}。"
        )

        # 由审判员发起并主导庭审辩论
        chat_result = self.PresidingJudge.initiate_chat(
            manager,
            message=initial_message
        )

        # === 阶段二：保存结果 ===
        final_conversation_history = []
        plaintiff_debate_index = 0
        defendant_debate_index = 0

        for msg in manager.groupchat.messages:
            new_msg = msg.copy()
            if new_msg.get('name') == "PlaintiffTeamDelegate" and '原告补充证据集和：' not in new_msg.get('content'):
                if plaintiff_debate_index < len(all_plaintiff_internal_debates):
                    new_msg['interconversation'] = all_plaintiff_internal_debates[plaintiff_debate_index]
                    plaintiff_debate_index += 1
            elif new_msg.get('name') == "DefendantTeamDelegate" and '被告补充证据集和：' not in new_msg.get('content'):
                if defendant_debate_index < len(all_defendant_internal_debates):
                    new_msg['interconversation'] = all_defendant_internal_debates[defendant_debate_index]
                    defendant_debate_index += 1
            final_conversation_history.append(new_msg)

        # 不存在就创建文件夹
        if not os.path.exists(out_dir):
            os.makedirs(out_dir)

        conversation_path = os.path.join(
            out_dir, f"{case_index}_conversation.json")
        with open(conversation_path, "w", encoding="utf-8") as f:
            json.dump(final_conversation_history, f,
                      indent=4, ensure_ascii=False)

        print(f"\n对话记录已保存到：{conversation_path}")

        # === 阶段三：计算本案例Law Articles指标 ===
        pred_data = extract_law_articles_from_messages(manager.groupchat.messages)
        art_p, art_r, art_f1 = compute_prf1(pred_data['pre_articles'], case_true_articles)
        type_p,type_r,type_f1 = compute_prf1(pred_data['pre_crimetype'], case_true_type)

        print(f'预测罪名的P,R,F1：\n{type_p,type_r,type_f1}')
        retrieval_overlap = len(set(retrieved_laws) & set(case_true_articles)) / len(case_true_articles) if case_true_articles else 0

        print(f"\n===== 案例 {case_index}: {CaseId} 模拟结束 =====\n")

        return {
            "index": case_index,
            "CaseId": CaseId,
            "Law_articles":{
                "pred_law_articles": sorted(list(set(pred_data['pre_articles']))),
                "true_law_articles": sorted(list(set(case_true_articles))),
                "precision": art_p,
                "recall": art_r,
                "f1": art_f1,
            },
            "crime_types":{
                "pred_crime_types": list(set(pred_data['pre_crimetype'])),
                "true_crime_types": list(set(case_true_type)),
                "precision": type_p,
                "recall": type_r,
                "f1": type_f1,
            },
            "retrieval_overlap": retrieval_overlap,
            "conversation_path": conversation_path,
        }

if __name__ == "__main__":
    # 从JSON文件中加载要模拟的案例
    inputDir = 'dataset/ours/judgeCases.json'
    out_dir = "ljp_output/10.20"
    checkpoint_file = os.path.join(out_dir, "checkpoint.json")

    try:
        with open(inputDir, "r", encoding="utf-8") as f:
            simulation_cases = json.load(f)
    except FileNotFoundError:
        print(f"错误：未找到{inputDir} 文件。请确保该文件存在于正确的目录中。")
        exit()
    except json.JSONDecodeError:
        print("错误：'cases.json' 文件格式不正确，无法解析。")
        exit() 

    # 创建输出目录
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # 尝试加载断点
    checkpoint_data = load_checkpoint(checkpoint_file)

    if checkpoint_data:
        # 从断点恢复
        results = checkpoint_data["results"]
        sum_art_p = checkpoint_data["law_articles"]["sum_art_p"]
        sum_art_r = checkpoint_data["law_articles"]["sum_art_r"]
        sum_art_f1 = checkpoint_data["law_articles"]["sum_art_f1"]
        sum_type_p = checkpoint_data["crime_type"]["sum_type_p"]
        sum_type_r = checkpoint_data["crime_type"]["sum_type_r"]
        sum_type_f1 = checkpoint_data["crime_type"]["sum_type_f1"]
        sum_retrieval_overlap = checkpoint_data["sum_retrieval_overlap"]
        case_cnt = checkpoint_data["case_cnt"]
        completed_indices = set(checkpoint_data["completed_indices"])
        skipped_cases = checkpoint_data.get("skipped_cases", [])
        print(f"从断点恢复：已完成 {case_cnt} 个案例")
    else:
        # 初始化新运行
        results = []
        sum_art_p = 0.0
        sum_art_r = 0.0
        sum_art_f1 = 0.0
        sum_type_p = 0.0
        sum_type_r = 0.0
        sum_type_f1 = 0.0
        sum_retrieval_overlap = 0
        case_cnt = 0
        completed_indices = set()
        skipped_cases = []
        print("开始新的运行...")

    # 依次运行所有模拟案例并统计指标
    court = CourtAgents()
    for case in simulation_cases:
        case_index = case["index"]
        case_id = case["CaseId"]

        if "index" not in case or 'case_description' not in case:
            print(f"警告：案件 '{case.get('CaseId', '未命名')}' 缺少'index'或'case_description'字段，将跳过此案件。")
            skipped_cases.append({
            "CaseId": case_id,
            "index": case_index,
            "reason": "missing index or case_description"
            })
            save_checkpoint(checkpoint_file,results,case_cnt,sum_art_p,sum_art_r,sum_art_f1,sum_type_p, sum_type_r, sum_type_f1,sum_retrieval_overlap,list(completed_indices),skipped_cases)
            continue

        # 检查是否已完成
        if is_case_completed(case_index, completed_indices):
            print(f"案例 {case_index} 已完成，跳过...")
            continue

        try:
            print(f"\n开始处理案例 {case_index}...")
            res = court.run_simulation(case, out_dir)
            results.append(res)
            sum_art_p += res["Law_articles"]["precision"]
            sum_art_r += res["Law_articles"]["recall"]
            sum_art_f1 += res["Law_articles"]["f1"]
            sum_type_p += res["crime_types"]["precision"]
            sum_type_r += res["crime_types"]["recall"]
            sum_type_f1 += res["crime_types"]["f1"]
            sum_retrieval_overlap += res['retrieval_overlap']
            case_cnt += 1
            completed_indices.add(case_index)

            # 每完成一个案例就保存断点
            save_checkpoint(checkpoint_file, results, case_cnt,sum_art_p, sum_art_r, sum_art_f1,sum_type_p, sum_type_r, sum_type_f1,sum_retrieval_overlap, list(completed_indices),skipped_cases)
            print(f"案例 {case_index} 处理完成，断点已保存")

        except Exception as e:
            print(f"处理案例 {case_index} 时发生错误：{e}")
            print("程序将停止，下次运行时将从断点继续...")
            # 保存当前进度
            save_checkpoint(checkpoint_file, results, case_cnt,sum_art_p, sum_art_r, sum_art_f1,sum_type_p, sum_type_r, sum_type_f1,sum_retrieval_overlap, list(completed_indices),skipped_cases)
            break

    if case_cnt > 0:
        avg_art_p = sum_art_p / case_cnt
        avg_art_r = sum_art_r / case_cnt
        avg_art_f1 = sum_art_f1 / case_cnt
        avg_type_p = sum_type_p / case_cnt
        avg_type_r = sum_type_r / case_cnt
        avg_type_f1 = sum_type_f1 / case_cnt
        avg_retrieval_overlap = sum_retrieval_overlap/case_cnt

        # 保存指标到文件
        metrics_output = {
            "per_case": results,
            "law_articles_average": {
                "precision": avg_art_p,
                "recall": avg_art_r,
                "f1": avg_art_f1,
            },
            "crime_type_average":{
                "precision": avg_type_p,
                "recall": avg_type_r,
                "f1": avg_type_f1,
            },
            "retrieval_overlap":avg_retrieval_overlap,
            "cases": case_cnt,
        }

        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
        with open(os.path.join(out_dir, "metrics.json"), "w", encoding="utf-8") as f:
            json.dump(metrics_output, f, ensure_ascii=False, indent=4)
        print(f"指标已保存至：{os.path.join(out_dir, 'metrics.json')}")
    else:
        print("无可统计的案例。")