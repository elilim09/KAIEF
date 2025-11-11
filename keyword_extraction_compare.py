import re
import time
import json
import matplotlib.pyplot as plt
from openai import OpenAI
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # 환경변수로 주입 권장
client = OpenAI(api_key=OPENAI_API_KEY)
sentences = [
    "무료 강연 좋은데 야외는 말고 실내 위주로. 어린이 프로그램은 빼줘.",
    "공연이나 음악회 같은 거 보고 싶어. 가족 단위는 좀...",
    "비 오는 날 가기 좋은 실내 체험 위주로 알려줘.",
    "야외 캠핑 같은 건 싫고 조용한 독서 모임 좋아해.",
    "아이랑 같이 할 수 있는 실내 과학 체험 알려줘.",
    "주차 편한 곳이면 좋겠고, 입장료는 무료면 좋겠어.",
]

ground_truth = [
    {"keywords": ["무료", "강연", "실내"], "excluded": ["야외", "어린이"]},
    {"keywords": ["공연", "음악회"], "excluded": ["가족"]},
    {"keywords": ["실내", "체험"], "excluded": []},
    {"keywords": ["독서", "모임"], "excluded": ["야외", "캠핑"]},
    {"keywords": ["아이", "실내", "과학", "체험"], "excluded": []},
    {"keywords": ["주차", "입장료", "무료"], "excluded": []},
]

stopwords = ['은','는','이','가','을','를','에','의','도','으로','로',
             '그리고','하지만','말고','위주','좋은데','에서','부터','까지','좀','은데','에는']

def extract_keywords_simple(text):
    tokens = re.findall(r"[가-힣]+", text)
    return [w for w in tokens if w not in stopwords and len(w) > 1]

def extract_excluded_simple(text):
    excluded = []
    tokens = text.split()
    for i, word in enumerate(tokens):
        if any(kw in word for kw in ['말고', '빼줘', '싫', '제외']):
            if i > 0:
                excluded.append(re.sub(r'[^가-힣]', '', tokens[i-1]))
    return excluded
def extract_keywords_ai(text):
    prompt = f"""
    다음 문장에서 핵심 키워드와 제외 키워드를 JSON으로 추출해줘.
    반드시 JSON만 출력해. 설명, 문장, 따옴표 밖 텍스트는 금지.
    예시:
    {{
      "keywords": ["무료","강연","실내"],
      "excluded": ["야외","어린이"]
    }}
    문장: "{text}"
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    content = response.choices[0].message.content.strip()

    content = re.sub(r"^```(json)?", "", content)
    content = re.sub(r"```$", "", content)
    content = content.strip()

    try:
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            data = json.loads(match.group())
            return data
    except Exception as e:
        print("⚠️ JSON 파싱 실패:", e, "\nAI 응답:", content)
    
    return {"keywords": [], "excluded": []}

def jaccard_similarity(set1, set2):
    if not set1 and not set2:
        return 1.0
    intersection = len(set(set1) & set(set2))
    union = len(set(set1) | set(set2))
    return intersection / union if union else 0

rule_results, ai_results = [], []
rule_times, ai_times = [], []

for sentence in sentences:
    start = time.time()
    kw_rule = extract_keywords_simple(sentence)
    ex_rule = extract_excluded_simple(sentence)
    rule_times.append(time.time() - start)
    rule_results.append({"keywords": kw_rule, "excluded": ex_rule})

  
    start = time.time()
    ai_data = extract_keywords_ai(sentence)
    ai_times.append(time.time() - start)
    ai_results.append(ai_data)


rule_acc, ai_acc = [], []

for i in range(len(sentences)):
    gt_kw = set(ground_truth[i]["keywords"])
    gt_ex = set(ground_truth[i]["excluded"])

  
    r_kw = set(rule_results[i]["keywords"])
    r_ex = set(rule_results[i]["excluded"])
    rule_score = (jaccard_similarity(gt_kw, r_kw) + jaccard_similarity(gt_ex, r_ex)) / 2
    rule_acc.append(rule_score)

  
    a_kw = set(ai_results[i]["keywords"])
    a_ex = set(ai_results[i]["excluded"])
    ai_score = (jaccard_similarity(gt_kw, a_kw) + jaccard_similarity(gt_ex, a_ex)) / 2
    ai_acc.append(ai_score)


for i, s in enumerate(sentences):
    print(f"\n문장 {i+1}: {s}")
    print(f"정답 → {ground_truth[i]}")
    print(f"규칙 기반 → {rule_results[i]} (정확도 {rule_acc[i]:.2f})")
    print(f"AI 기반 → {ai_results[i]} (정확도 {ai_acc[i]:.2f})")
    print(f"처리속도: 규칙 {rule_times[i]:.4f}s / AI {ai_times[i]:.2f}s")

plt.figure(figsize=(8, 5))
plt.plot(range(1, len(sentences)+1), rule_acc, marker='o', label='rule')
plt.plot(range(1, len(sentences)+1), ai_acc, marker='s', linestyle='--', label='ai')
plt.title("rule vs AI ")
plt.xlabel("number")
plt.ylabel("Jaccard Similarity")
plt.ylim(0, 1.05)
plt.legend()
plt.grid(True)
plt.show()
