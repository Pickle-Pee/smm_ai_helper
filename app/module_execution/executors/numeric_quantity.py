"""Bounded quantity detection, never numerical parsing or source normalization."""
import re


_DIGIT = re.compile(r"\d")  # Preserve the existing Unicode decimal-digit boundary.
_WORD = re.compile(r"[^\W\d_]+")
_GAP = re.compile(r"[\s\-‐‑‒–—]*")

# Explicit forms: this is not a morphological parser or a general language model.
_CARDINALS = frozenset("""
zero one two three four five six seven eight nine ten eleven twelve thirteen
fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty
sixty seventy eighty ninety hundred thousand single
ноль нуль нуля нулю нулем нулём нуле
один одна одно одну одного одной одному одним одном одни одних одними
два две двух двум двумя три трех трёх трем трём тремя
четыре четырех четырёх четырем четырём четырьмя
пять пяти пятью шесть шести шестью семь семи семью восемь восьми восемью восьмью
девять девяти девятью десять десяти десятью
одиннадцать одиннадцати одиннадцатью двенадцать двенадцати двенадцатью
тринадцать тринадцати тринадцатью четырнадцать четырнадцати четырнадцатью
пятнадцать пятнадцати пятнадцатью шестнадцать шестнадцати шестнадцатью
семнадцать семнадцати семнадцатью восемнадцать восемнадцати восемнадцатью
девятнадцать девятнадцати девятнадцатью двадцать двадцати двадцатью
тридцать тридцати тридцатью сорок сорока пятьдесят пятидесяти пятьюдесятью
шестьдесят шестидесяти шестьюдесятью семьдесят семидесяти семьюдесятью
восемьдесят восьмидесяти восемьюдесятью девяносто девяноста сто ста
тысяча тысячи тысячу тысяч тысячей тысячами тысячам тысячах
""".split())
_UNITS = frozenset("""
visit visits session sessions question questions step steps action actions
participant participants person persons people customer customers client clients
item items image images photo photos task tasks group groups option options
experiment experiments hypothesis hypotheses trial trials cohort cohorts
minute minutes hour hours day days week weeks month months year years
ruble rubles rouble roubles dollar dollars euro euros percent percentage points
визит визита визитов визиту визитам визитом визитами визите визитах визиты
посещение посещения посещений посещению посещениям посещением посещениями посещении посещениях
занятие занятия занятий занятию занятиям занятием занятиями занятии занятиях
вопрос вопроса вопросов вопросу вопросам вопросом вопросами вопросе вопросах вопросы
шаг шага шагов шагу шагам шагом шагами шаге шагах шаги
действие действия действий действию действиям действием действиями действии действиях
участник участника участников участнику участникам участником участниками участнике участниках участники
человек человека людей человеку людям человеком людьми человеке людях
клиент клиента клиентов клиенту клиентам клиентом клиентами клиенте клиентах клиенты
предмет предмета предметов предмету предметам предметом предметами предмете предметах предметы
изделие изделия изделий изделию изделиям изделием изделиями изделии изделиях
снимок снимка снимков снимку снимкам снимком снимками снимке снимках снимки
фотография фотографии фотографий фотографию фотографиям фотографией фотографиями фотографиях
задание задания заданий заданию заданиям заданием заданиями задании заданиях
группа группы групп группу группам группой группами группе группах
вариант варианта вариантов варианту вариантам вариантом вариантами варианте вариантах варианты
эксперимент эксперимента экспериментов эксперименту экспериментам экспериментом экспериментами эксперименте экспериментах эксперименты
гипотеза гипотезы гипотез гипотезу гипотезам гипотезой гипотезами гипотезе гипотезах
поток потока потоков потоку потокам потоком потоками потоке потоках потоки
минута минуты минут минуту минутам минутой минутами минуте минутах
час часа часов часу часам часом часами часе часах часы
день дня дней дню дням днем днём днями дне днях дни
неделя недели недель неделю неделям неделей неделями неделе неделях
месяц месяца месяцев месяцу месяцам месяцем месяцами месяце месяцах месяцы
год года годов лет году годам годом годами годе годах годы
рубль рубля рублей рублю рублям рублем рублём рублями рубле рублях рубли
доллар доллара долларов доллару долларам долларом долларами долларе долларах доллары
евро процент процента процентов проценту процентам процентом процентами проценте процентах проценты
""".split())
_MODIFIERS = frozenset("""
short brief additional new paid initial simple quick small full complete
короткий короткая короткое короткие короткого короткой коротких короткому коротким короткую короткими коротком
краткий краткая краткое краткие краткого краткой кратких краткому кратким краткую краткими кратком
дополнительный дополнительная дополнительное дополнительные дополнительного дополнительной дополнительных дополнительному дополнительным дополнительную дополнительными дополнительном
новый новая новое новые нового новой новых новому новым новую новыми новом
платный платная платное платные платного платной платных платному платным платную платными платном
простой простая простое простые простого простой простых простому простым простую простыми простом
быстрый быстрая быстрое быстрые быстрого быстрой быстрых быстрому быстрым быструю быстрыми быстром
полный полная полное полные полного полной полных полному полным полную полными полном
""".split())


def has_numeric_quantity(text: str) -> bool:
    """Detect digits or an explicit cardinal followed by a recognized unit.

    At most two listed modifiers may intervene, separated by whitespace/hyphens.
    No arbitrary words or sentence punctuation are crossed: `one of the visits`,
    `one should visit`, ordinals and `first customers` are not counted phrases.
    Neither the input text nor its numerical meaning is rewritten or calculated.
    """
    if _DIGIT.search(text):
        return True
    words = list(_WORD.finditer(text))
    for index, word in enumerate(words):
        if word.group().casefold() not in _CARDINALS:
            continue
        previous = word
        for offset in range(1, 4):
            if index + offset >= len(words):
                break
            following = words[index + offset]
            if not _GAP.fullmatch(text[previous.end():following.start()]):
                break
            token = following.group().casefold()
            if token in _UNITS:
                return True
            if token not in _MODIFIERS:
                break
            previous = following
    return False
