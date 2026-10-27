"""AI 문장의 방향·의미 점검용 정규식. 숫자는 맞아도 해석이 뒤집힌 문장을 잡는다(실제 LLM 출력 2026-10-27에서 발견된 유형).

각 식은 한 문장 안에서만 찾는다(`[^.\n]`는 마침표·줄바꿈을 넘지 않는다).
판단에 쓰는 사실(계획 ≥ 법정, 자료 유무)은 app/facts.py의 FactTable이 갖고, 여기서는 '표현 패턴'만 정의한다.
"""
import re

# 계획 주차대수가 법정 이상인데 부족하다고 쓰거나 주차대수를 늘리라고 제안한 경우
PARKING_SHORTAGE = re.compile(
    r"주차\s*(?:공간|대수|시설)?(?:이|가|은|는)?[^.\n]{0,10}부족"
    r"|법정[^.\n]{0,12}미달"
    r"|주차\s*공간\s*확보가\s*이루어지지"
    r"|주차\s*(?:공간|대수)[^.\n]{0,12}(?:늘리|증설|추가(?:로)?\s*확보|확대)"
    r"|계획[^.\n]{0,10}주차[^.\n]{0,12}(?:늘리|증설|확대)"
)

# 부정어가 붙어도 '부족'을 뜻하는 표현(예: 주차 공간 확보가 이루어지지 않은 상태)
SHORTAGE_BY_NEGATION = re.compile(r"주차\s*(?:공간|대수|시설)?\s*확보[^.\n]{0,6}(?:이루어지지|되지|못)")

NEGATION_AFTER = re.compile(r"^[^.\n]{0,6}?(?:않|없|아니|못|아닙|문제는\s*발생하지|문제가\s*없)")
# '주차대수를 늘리는 방안은 적절하지 않다'처럼 늘리는 것 자체를 부정하는 올바른 문장
REJECTED_INCREASE = re.compile(r"^[^.\n]{0,14}?(?:적절하지|바람직하지|불필요|필요(?:는|가)?\s*(?:하지\s*)?(?:않|없)|제안하지|권고하지|하지\s*(?:않|아니))")
# 자전거·이륜차 주차는 승용차 주차대수 판정과 무관하다
OTHER_PARKING = re.compile(r"(?:자전거|이륜|오토바이|킥보드|보행)[^.\n]{0,4}$")


def parking_shortage_claims(text: str) -> list[str]:
    """계획이 법정 이상일 때 문제가 되는 문장 조각을 돌려준다. '부족하지 않다'처럼 부정이 바로 따르면 올바른 문장이므로 제외한다.

    매치 뒤 6자 안에 부정어(않·없·아니·못)가 있거나 '부족 문제는 발생하지'처럼 이어지면 건너뛴다.
    """
    claims = []
    for sent in split_sentences(text):
        if SHORTAGE_BY_NEGATION.search(sent):  # '확보가 이루어지지 않은'처럼 부정형 자체가 부족을 뜻하는 표현은 예외 없이 문제
            claims.append(sent.strip())
            continue
        for m in PARKING_SHORTAGE.finditer(sent):
            tail = sent[m.end():]
            if OTHER_PARKING.search(sent[max(0, m.start() - 8):m.start()]) or REJECTED_INCREASE.match(tail):
                continue
            if NEGATION_AFTER.match(tail) or re.match(r"^\s*(?:문제|우려)[^.\n]{0,8}(?:않|없)", tail):
                continue
            claims.append(sent.strip())
            break
    return claims


# 법정 대수와 원단위법 수요는 서로 다른 기준인데 한쪽이 다른 쪽을 '초과'한다고 쓴 경우
DEMAND_OVER_LEGAL = re.compile(
    r"(?:주차\s*)?수요(?:가|는|이)?[^.\n]{0,8}법정[^.\n]{0,10}초과"
    r"|법정[^.\n]{0,10}수요[^.\n]{0,8}초과"
)

# 입력에 없는 대중교통·보행·자전거 이용 수준을 단정한 경우
UNSUPPORTED_USE = re.compile(
    r"(?:대중교통|보행|자전거)[^.\n]{0,14}(?:이용|의존|분담)[^.\n]{0,24}(?:낮(?!추)|높(?!이|일)|저조|부족|미흡|활발|많은|많다|많습|적은|적다|적습)"
)

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n")


def split_sentences(text: str) -> list[str]:
    """마침표·물음표·느낌표 뒤 공백, 줄바꿈 기준으로 문장을 나눈다."""
    return [s for s in SENTENCE_SPLIT.split(text) if s.strip()]


# 같은 문장에 이 표현이 있으면 '자료가 없다'고 정직하게 쓴 것이므로 단정으로 보지 않는다
NO_DATA_HEDGE = re.compile(r"(?:자료|정보|데이터)[^.\n]{0,12}?(?:없|입력되지|확보되지|부족)|조사\s*(?:가\s*)?필요|단정[^.\n]{0,8}(?:불가|어렵|하지)|판단이?\s*(?:불가|어렵)|확인\s*(?:되지|불가)")

# 유입·유출(같은 시간대의 방향별 값)을 시간 변화로 풀이한 경우
INOUT_AS_TREND = re.compile(
    r"유입[^.\n]{0,14}(?:에서|→)[^.\n]{0,14}(?:까지|로)\s*(?:증가|감소|상승|하락)"
    r"|(?:증가|감소)[^.\n]{0,10}유입[^.\n]{0,10}유출"
)


# 교차로 지체·LOS 문장에서 분석하지 않은 첨두(AM/PM)를 언급한 경우 판별용
PEAK_AM = re.compile(r"AM|오전")
PEAK_PM = re.compile(r"PM|오후")
INTERSECTION_RESULT = re.compile(r"LOS|지체|v/c|포화")


def mentioned_peaks(sent: str) -> set[str]:
    return ({"am"} if PEAK_AM.search(sent) else set()) | ({"pm"} if PEAK_PM.search(sent) else set())
