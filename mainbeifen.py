from autogen import (UserProxyAgent, AssistantAgent, GroupChat, GroupChatManager,config_list_from_json)
import time
import json
import os

# === 全局配置 ===
N_ROUNDS = 10
config_list = config_list_from_json(env_or_file="configs/config_list.json")
MODEL_CONFIG = {
    "config_list": config_list,
    "cache_seed": None,
    "temperature": 1,
    "timeout": 300,
}

def run_simulation(case_data: dict):
    """
    运行一个完整的法庭模拟案例。

    :param case_data: 包含案件所有信息的字典，应包含 'index', 'CaseId', 'case_description, "defendant_evidence","plaintiff_evidence"'
    """
    case_index = case_data['index']
    CaseId = case_data['CaseId']
    case_description = case_data['case_description']
    defendant_evidence = case_data['defendant_evidence']
    plaintiff_evidence = case_data['plaintiff_evidence']

    
    print(f"\n===== 正在运行模拟案例 {case_index}: {CaseId} =====\n")

    # 讨论结束判断类
    class CourtTerminator:
        def __init__(self, max_rounds):
            self.round_count = 0
            self.max_rounds = max_rounds

        def __call__(self, x):
            self.round_count += 1
            # 只在达到最大轮数时结束对话
            return self.round_count >= self.max_rounds

    terminator = CourtTerminator(max_rounds=N_ROUNDS)

    # 用于收集所有内部讨论历史的列表
    all_plaintiff_internal_debates = []
    all_defendant_internal_debates = []
    
    # === 创建审判长 (最后宣判) ===
    PresidingJudge = AssistantAgent(
        name="PresidingJudge",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是一名公正中立的审判长。你的任务是审查完整的庭审辩论记录，并在此基础上做出最终判决。"
            "你的判决应该是全面的，考虑到所有提出的证据、论点和各方意见。"
            "请严格按照以下格式输出："
            "【案件事实】：……"
            "【证据与理由】：……"
            "【最终判决如下】：明确写明罪名、量刑、罚金金额（如有）、附加刑（如有）、以及适用的法律条款。"
        )

    )

    # === 创建审判员 (主导辩论) ===
    Adjudicator = AssistantAgent(
        name="Adjudicator",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是一名公正严谨的审判员。你的职责是主持庭审，"
            "引导原告与被告围绕案件核心问题展开有序辩论，确保程序公正与充分辩论。"
            "在庭审过程中，你需要："
            "1. 积极询问双方当事人，核实关键事实；"
            "2. 审查和质证证据，确保其真实性与关联性；"
            "3. 针对争议焦点提出专业性意见，提示法律适用问题；"
            "4. 控制庭审节奏，保证讨论在规定轮次内充分进行。"
            "请始终保持中立、公正，并引导庭审向清晰、有效的结论推进。"
        )
    )

    # === 创建原告团队成员 ===
    PlaintiffLeadCounsel = AssistantAgent(
        name="PlaintiffLeadCounsel",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是原告首席律师，负责领导团队并制定整体诉讼策略。"
            "你的任务是：组织团队讨论，协调证据专家、法律研究员和客户联络人的意见，"
            "并将团队的内部讨论结果整合成一份逻辑清晰、具有说服力的最终意见。"
            "你不直接在法庭上发言，你的意见会交由原告团队代表在法庭上传达。"
            f"案件描述: {case_description}"
        )
    )

    PlaintiffEvidenceSpecialist = AssistantAgent(
        name="PlaintiffEvidenceSpecialist",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是原告证据专家，专注于案件中提供的证据。"
            "你的任务是：全面分析案件描述中的所有证据，筛选对原告有利的部分，"
            "协助团队合理地举证，并在庭审中帮助反驳对方对证据的质疑。"
            "你不得编造或扩展案件之外的证据，必须严格基于案件描述进行分析。"
            "你不需要进行法律条文研究或发言总结。"
            f"案件描述: {case_description}"
        )
    )

    PlaintiffLegalResearcher = AssistantAgent(
        name="PlaintiffLegalResearcher",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是原告法律研究员，专注于法律依据和判例支持。"
            "你的任务是：为团队提供与案件相关的法律条文、司法解释和判例，"
            "确保原告的论点在法律上站得住脚，并为反驳被告的法律主张提供依据。"
            "你不负责证据分析或客户诉求表达，只需从法律角度提供专业见解。"
            f"案件描述: {case_description}"
        )
    )

    PlaintiffClientLiaison = AssistantAgent(
        name="PlaintiffClientLiaison",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是原告客户联络人，唯一任务是代表原告的利益与意愿。"
            "你的职责是：确保团队的论点与原告的核心诉求保持一致，"
            "在内部讨论中传达原告的关切和优先目标，提醒团队不要偏离原告真正关心的问题。"
            "你不负责法律研究或证据分析，但你的意见对团队整体策略具有指导作用。"
            f"案件描述: {case_description}"
        )
    )

    # === 创建原告团队内部群聊 ===
    plaintiff_internal_agents = [PlaintiffLeadCounsel, PlaintiffEvidenceSpecialist, PlaintiffLegalResearcher, PlaintiffClientLiaison]
    plaintiff_internal_groupchat = GroupChat(
        agents=plaintiff_internal_agents,
        messages=[],
        max_round=5, # 内部讨论轮次可以少一些
        speaker_selection_method="round_robin",
        allow_repeat_speaker=False, # 内部讨论不应该重复发言人
        select_speaker_auto_verbose=False # 设置为True会展示为什么选择这个人
    )
    plaintiff_internal_manager = GroupChatManager(
        groupchat=plaintiff_internal_groupchat,
        llm_config=MODEL_CONFIG
    )

    # === 创建原告团队发言人 ===
    class PlaintiffTeamDelegate(AssistantAgent):
        def __init__(self, *args, **kwargs):
            self.internal_manager = kwargs.pop("internal_manager")
            self.case_description = kwargs.pop("case_description")
            self.all_internal_debates = kwargs.pop("all_internal_debates") # 添加此行以接收列表
            filtered_kwargs = {k: v for k, v in kwargs.items()}
            super().__init__(*args, **filtered_kwargs)

        def generate_reply(self, messages=None, sender=None, exclude=None, **kwargs):
            # The last message from the main group chat is the one to be discussed internally.
            last_message_from_court = messages[-1]["content"] if messages else ""

            print(f"\n--- PlaintiffTeamDelegate 收到法庭消息，转发给内部团队讨论 ---")
            internal_message = (
                f"案件描述: {self.case_description}\n\n"
                f"法庭传来消息：{last_message_from_court}\n\n"
                "请团队成员（首席律师、证据专家、法律研究员、客户联络人）仔细分析法庭消息。"
                "围绕案件描述和法庭消息进行充分讨论，并生成一个针对法庭消息的统一、清晰、有力的回复。"
                "首席律师需要在讨论结束后，对团队讨论的结果进行总结，并确保最终的回复是原创的，并且内容与法庭消息或案件描述有显著区别。"
            )

            # Initiate an internal chat with the plaintiff team
            # Setting silent=True to avoid verbose output of internal chat to the main console
            plaintiff_internal_chat_result = self.initiate_chat(
                self.internal_manager,
                message=internal_message,
                # silent=True # 移除此行
            )

            # Extract the internal debate history, skipping the initial prompt from PlaintiffTeamDelegate
            internal_debate_history = self.internal_manager.groupchat.messages[:] if len(self.internal_manager.groupchat.messages) > 1 else []
            self.all_internal_debates.append(internal_debate_history) # 将本次内部讨论历史追加到列表中
            team_reply = "原告团队内部未能达成一致意见。" # Default reply

            if internal_debate_history:
                # 优先寻找首席律师的最后一条消息
                lead_counsel_replies = [msg for msg in internal_debate_history if msg.get('name') == "PlaintiffLeadCounsel"]
                if lead_counsel_replies:
                    team_reply = lead_counsel_replies[-1]['content']
                else:
                    # 如果没有首席律师的回复，则使用内部讨论中的最后一条消息
                    team_reply = internal_debate_history[-1]['content']

            print(f"\n--- PlaintiffTeamDelegate 将内部团队讨论结果作为发言 ---")
            return {
                "content": team_reply,
            }

    PlaintiffTeamDelegate = PlaintiffTeamDelegate(
        name="PlaintiffTeamDelegate",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是原告团队在法庭上的唯一代表，负责正式发言。"
            "你的任务是接收法庭信息，将其传递给原告团队内部进行讨论，"
            "并在团队首席律师整合出最终意见后，将该意见忠实地作为你的发言提交给法庭。"
            "你不能自行生成或修改观点，你的职责仅是忠实、准确地传达原告团队的集体意见。"
        ),
        internal_manager=plaintiff_internal_manager,
        case_description=case_description,
        all_internal_debates=all_plaintiff_internal_debates # 传递列表
    )

    # === 创建被告团队成员 ===
    DefendantLeadCounsel = AssistantAgent(
        name="DefendantLeadCounsel",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是被告首席律师，负责领导和协调整个被告团队。"
            "你的任务是组织团队讨论，整合证据专家、法律研究员和客户联络人的意见，"
            "并将这些意见汇总成逻辑清晰、具有说服力的最终辩护立场。"
            "你不直接在法庭上发言，你的最终意见将交由被告团队代表在法庭上传达。"
            f"案件描述: {case_description}"
        )
    )

    DefendantEvidenceSpecialist = AssistantAgent(
        name="DefendantEvidenceSpecialist",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是被告证据专家，专注于案件描述中提供的证据。"
            "你的任务是全面分析证据，找出对被告有利的部分，"
            "并帮助团队在庭审中有效地呈现这些证据，反驳原告对证据的质疑。"
            "你不能编造或补充案件之外的新证据，只能基于案件描述进行分析。"
            "你不负责法律条文研究或客户诉求表达。"
            f"案件描述: {case_description}"
        )
    )

    DefendantLegalResearcher = AssistantAgent(
        name="DefendantLegalResearcher",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是被告法律研究员，专注于法律依据和判例支持。"
            "你的任务是为团队提供与案件相关的法律条文、司法解释和判例，"
            "确保被告的论点在法律上站得住脚，并能有效回应原告提出的法律主张。"
            "你不负责证据分析或客户诉求表达，只需从法律角度提供专业见解。"
            f"案件描述: {case_description}"
        )
    )

    DefendantClientLiaison = AssistantAgent(
        name="DefendantClientLiaison",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是被告客户联络人，代表被告的个人利益和意愿。"
            "你的任务是确保团队的论点与被告的核心诉求一致，"
            "在内部讨论中传达被告的关注点和优先目标，提醒团队保持与当事人利益的紧密联系。"
            "你不参与具体的法律研究或证据分析，但你的意见对团队整体策略具有指导作用。"
            f"案件描述: {case_description}"
        )
    )

    # === 创建被告团队内部群聊 ===
    defendant_internal_agents = [DefendantLeadCounsel, DefendantEvidenceSpecialist, DefendantLegalResearcher, DefendantClientLiaison]
    defendant_internal_groupchat = GroupChat(
        agents=defendant_internal_agents,
        messages=[],
        max_round=5, # 内部讨论轮次可以少一些
        speaker_selection_method="round_robin",
        allow_repeat_speaker=False, # 内部讨论不应该重复发言人
        select_speaker_auto_verbose=False # 设置为True会展示为什么选择这个人
    )
    defendant_internal_manager = GroupChatManager(
        groupchat=defendant_internal_groupchat,
        llm_config=MODEL_CONFIG
    )

    # === 创建被告团队发言人 ===
    class DefendantTeamDelegate(AssistantAgent):
        def __init__(self, *args, **kwargs):
            self.internal_manager = kwargs.pop("internal_manager")
            self.case_description = kwargs.pop("case_description")
            self.all_internal_debates = kwargs.pop("all_internal_debates") # 添加此行以接收列表
            filtered_kwargs = {k: v for k, v in kwargs.items()}
            super().__init__(*args, **filtered_kwargs)

        def generate_reply(self, messages=None, sender=None, exclude=None, **kwargs):
            # The last message from the main group chat is the one to be discussed internally.
            last_message_from_court = messages[-1]["content"] if messages else ""

            print(f"\n--- DefendantTeamDelegate 收到法庭消息，转发给内部团队讨论 ---")
            internal_message = (
                f"案件描述: {self.case_description}\n\n"
                f"法庭传来消息：{last_message_from_court}\n\n"
                "请团队成员（首席律师、证据专家、法律研究员、客户联络人）仔细分析法庭消息。"
                "围绕案件描述和法庭消息进行充分讨论，并生成一个针对法庭消息的统一、清晰、有力的回复。"
                "首席律师需要在讨论结束后，对团队讨论的结果进行总结，并确保最终的回复是原创的，并且内容与法庭消息或案件描述有显著区别。"
            )

            # Initiate an internal chat with the defendant team
            defendant_internal_chat_result = self.initiate_chat(
                self.internal_manager,
                message=internal_message,
            )

            # Extract the internal debate history, skipping the initial prompt from DefendantTeamDelegate
            internal_debate_history =   self.internal_manager.groupchat.messages[:] if len(self.internal_manager.groupchat.messages) >= 1 else []
            self.all_internal_debates.append(internal_debate_history) # 将本次内部讨论历史追加到列表中
            team_reply = "被告团队内部未能达成一致意见。" # Default reply

            if internal_debate_history:
                # 优先寻找首席律师的最后一条消息
                lead_counsel_replies = [msg for msg in internal_debate_history if msg.get('name') == "DefendantLeadCounsel"]
                if lead_counsel_replies:
                    team_reply = lead_counsel_replies[-1]['content']
                else:
                    # 如果没有首席律师的回复，则使用内部讨论中的最后一条消息
                    team_reply = internal_debate_history[-1]['content']

            print(f"\n--- DefendantTeamDelegate 将内部团队讨论结果作为发言 ---")
            return {
                "content": team_reply,
            }

    DefendantTeamDelegate = DefendantTeamDelegate(
        name="DefendantTeamDelegate",
        llm_config=MODEL_CONFIG,
        system_message=(
            "你是被告团队在法庭上的唯一代表，负责正式发言。"
            "你的任务是接收法庭信息，将其转交给被告团队内部进行讨论，"
            "并在首席律师整合出最终意见后，将该意见忠实地作为你的发言呈现给法庭。"
            "你不能添加、修改或删除团队的观点，你的职责是准确、忠实地传达团队的集体意见。"
        ),
        internal_manager=defendant_internal_manager,
        case_description=case_description,
        all_internal_debates=all_defendant_internal_debates # 传递列表
    )

    # === 构建群体对话系统 ===
    debate_agents = [Adjudicator, PresidingJudge, PlaintiffTeamDelegate, DefendantTeamDelegate]
    groupchat = GroupChat(
        agents=debate_agents,
        messages=[],
        max_round=N_ROUNDS,
        speaker_selection_method="auto",
        allow_repeat_speaker=False,
        select_speaker_auto_verbose=False
    )

    manager = GroupChatManager(
        groupchat=groupchat,
        llm_config=MODEL_CONFIG,
        is_termination_msg=terminator
    )

    # === 阶段一：庭审辩论 ===
    time.sleep(3)
    initial_message = (
        f"法庭辩论现在开始。\n【案件编号】: {case_index}\n【案件ID】: {CaseId}\n"
        f"【案情简介】: {case_description}\n\n"
        "我作为审判员将主导本次辩论。原告团队，请提出你的开场陈述，陈述你方的诉求和证据。"
        "请注意，在辩论过程中，各方只能使用案件描述中提供的信息和证据。"
    )
    
    # 由审判员发起并主导庭审辩论
    chat_result = Adjudicator.initiate_chat(
        manager,
        message=initial_message
    )

    # === 阶段二：保存结果 ===
    final_conversation_history = []
    plaintiff_debate_index = 0
    defendant_debate_index = 0

    print(f"all_plaintiff_internal_debates:\n{all_plaintiff_internal_debates}")

    print(f"all_defendant_internal_debates:\n{all_defendant_internal_debates}")

    for msg in manager.groupchat.messages:
        new_msg = msg.copy()
        if new_msg.get('name') == "PlaintiffTeamDelegate":
            if plaintiff_debate_index < len(all_plaintiff_internal_debates):
                new_msg['interconversation'] = all_plaintiff_internal_debates[plaintiff_debate_index]
                plaintiff_debate_index += 1
        elif new_msg.get('name') == "DefendantTeamDelegate":
            if defendant_debate_index < len(all_defendant_internal_debates):
                new_msg['interconversation'] = all_defendant_internal_debates[defendant_debate_index]
                defendant_debate_index += 1
        final_conversation_history.append(new_msg)

    output_dir = "ljp_output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    conversation_path = os.path.join(output_dir, f"{case_index}_conversation.json")
    with open(conversation_path, "w", encoding="utf-8") as f:
        json.dump(final_conversation_history, f, indent=4, ensure_ascii=False)

    print(f"\n对话记录已保存到：{conversation_path}")
    print(f"\n===== 案例 {case_index}: {CaseId} 模拟结束 =====\n")


if __name__ == "__main__":
    # 从JSON文件中加载要模拟的案例
    inputDir = 'dataset/ours/processed_cases.json'
    try:
        with open(inputDir, "r", encoding="utf-8") as f:
            simulation_cases = json.load(f)
    except FileNotFoundError:
        print(f"错误：未找到{inputDir} 文件。请确保该文件存在于正确的目录中。")
        exit()
    except json.JSONDecodeError:
        print("错误：'cases.json' 文件格式不正确，无法解析。")
        exit()


    # 依次运行所有模拟案例
    for case in simulation_cases:
        if "index" not in case:
            print(f"警告：案件 '{case.get('CaseId', '未命名')}' 缺少 'index' 字段，将跳过此案件。")
            continue
        run_simulation(case)