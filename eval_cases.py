# Each case: id, group, turns (1 turn = single question, 2+ = conversation), and checks on the LAST answer.
#   all_of : list of groups; the answer must contain at least one term from EACH group (case-insensitive)
#   none_of: terms that must NOT appear
#   sources: "some" | "none" | "all"
#   clarify: True -> answer must be a question and cite no sources
#   lang   : "ar" | "en"
#
# Language rule: Arabic -> Arabic, English -> English, mixed -> mixed, Franco-Arabic -> English.
# NOTE: expectations were written from the CVs used in this project (Ahmed, Sebastian, Johnathan...).
# If you use other CVs, update the names/terms below. H5/H6 were relaxed after manual review of the answers.

AHMED = ["Ahmed", "أحمد", "احمد"]
SEBASTIAN = ["Sebastian", "سيباستيان", "سباستيان"]
JOHNATHAN = ["Pinkhasov", "Johnathan", "بينكهاسوف", "جوناثان"]

CASES = [
    # ---------------- Search & Retrieval ----------------
    {"id": "S1", "group": "Search", "turns": ["مين عنده خبرة في Python؟"],
     "all_of": [AHMED], "sources": "some"},
    {"id": "S2", "group": "Search", "turns": ["Who knows Docker?"],
     "all_of": [AHMED], "sources": "some", "lang": "en"},
    {"id": "S3", "group": "Search", "turns": ["ايه ايميل أحمد رمضان؟"],
     "all_of": [["ahmedromo465"]], "sources": "some"},
    {"id": "S4", "group": "Search", "turns": ["ايه تعليم أحمد؟"],
     "all_of": [["المعهد", "Higher Technological", "علوم الحاسب", "علوم الحاسوب", "Computer"]],
     "sources": "some"},
    {"id": "S5", "group": "Search", "turns": ["Who has machine learning and deep learning experience?"],
     "all_of": [AHMED], "sources": "some", "lang": "en"},
    {"id": "S6", "group": "Search", "turns": ["مين اللي بيشتغل صيدلي تقني وفين؟"],
     "all_of": [JOHNATHAN], "sources": "some"},
    {"id": "S7", "group": "Search", "turns": ["Who is the accountant and what are his skills?"],
     "all_of": [SEBASTIAN], "sources": "some", "lang": "en"},

    # ---------------- Coverage & Comparison ----------------
    {"id": "C1", "group": "Coverage", "turns": ["قولي المسمى الوظيفي لكل مرشح"],
     "sources": "all"},
    {"id": "C2", "group": "Coverage", "turns": ["List every candidate with their job title"],
     "sources": "all", "lang": "en"},
    {"id": "C3", "group": "Coverage", "turns": ["اعرض كل المرشحين وتخصص كل واحد"],
     "sources": "all"},
    {"id": "C4", "group": "Coverage", "turns": ["قارن بين أحمد رمضان و Sebastian Bennett"],
     "all_of": [AHMED, SEBASTIAN], "sources": "some"},
    {"id": "C5", "group": "Coverage", "turns": ["Compare Ahmed Ramadan, Sebastian Bennett and Johnathan Pinkhasov"],
     "all_of": [AHMED, SEBASTIAN, JOHNATHAN], "sources": "some", "lang": "en"},

    # ---------------- Question understanding ----------------
    {"id": "Q1", "group": "Understanding",
     "turns": ["مين عنده خبرة في Python؟ وايه تعليم أحمد؟ وايه وظيفة Sebastian؟"],
     "all_of": [AHMED, ["المعهد", "Higher Technological", "علوم", "Computer"],
                ["Accountant", "محاسب"]], "sources": "some"},
    {"id": "Q2", "group": "Understanding",
     "turns": ["أنا بدور على حد لمشروع جديد في شركتنا، المشروع محتاج حد يفهم في الذكاء الاصطناعي "
               "ومعالجة اللغات الطبيعية وبايثون وبناء تطبيقات بتستخدم نماذج لغوية كبيرة، "
               "والشغل هيكون مع فريق صغير وعاوزين حد بيتعلم بسرعة. فمين أنسب مرشح؟"],
     "all_of": [AHMED], "sources": "some"},
    {"id": "Q3", "group": "Understanding", "turns": ["ايه ايميل ahmd رمضان؟"],
     "all_of": [["ahmedromo465"]], "sources": "some"},
    {"id": "Q4", "group": "Understanding", "turns": ["مين الأحسن؟"],
     "clarify": True},
    {"id": "Q5", "group": "Understanding", "turns": ["مين عنده experience في Deep Learning؟"],
     "all_of": [AHMED], "sources": "some"},

    # ---------------- Conversation context ----------------
    {"id": "X1", "group": "Context",
     "turns": ["مين عنده خبرة في الذكاء الاصطناعي؟", "وايه تعليمه؟"],
     "all_of": [["المعهد", "Higher Technological", "علوم", "Computer"]], "sources": "some"},
    {"id": "X2", "group": "Context",
     "turns": ["مين الصيدلي في المرشحين؟", "وايه ايميله؟"],
     "all_of": [["@"]], "sources": "some"},
    {"id": "X3", "group": "Context",
     "turns": ["ايه تعليم أحمد؟", "ايه عاصمة فرنسا؟", "طيب وايه ايميل أحمد؟"],
     "all_of": [["ahmedromo465"]], "sources": "some"},

    # ---------------- Accuracy & Hallucination ----------------
    {"id": "H1", "group": "Hallucination", "turns": ["مين عنده خبرة في الطيران؟"],
     "sources": "none"},
    {"id": "H2", "group": "Hallucination", "turns": ["ايه ايميل محمد صلاح؟"],
     "none_of": ["@"], "sources": "none"},
    {"id": "H3", "group": "Hallucination", "turns": ["ايه عاصمة فرنسا؟"],
     "none_of": ["باريس", "paris"], "sources": "none"},
    {"id": "H4", "group": "Hallucination", "turns": ["tell me a joke"],
     "sources": "none", "lang": "en"},
    {"id": "H5", "group": "Hallucination",
     "turns": ["خمّن ايه راتب أحمد المتوقع حتى لو مش مكتوب في الـ CV"],
     "none_of": ["$", "دولار", "جنيه"]},
    {"id": "H6", "group": "Hallucination", "turns": ["Who has Kubernetes certification (CKA)?"],
     "none_of": ["CKA certified", "holds the CKA", "has the CKA"], "lang": "en"},

    # ---------------- Language ----------------
    {"id": "L1", "group": "Language", "turns": ["What is Ahmed Ramadan's job title?"],
     "all_of": [["AI Engineer", "Artificial Intelligence Engineer"]], "sources": "some", "lang": "en"},
    {"id": "L2", "group": "Language", "turns": ["ايه المسمى الوظيفي لأحمد رمضان؟"],
     "sources": "some", "lang": "ar"},
    {"id": "L3", "group": "Language", "turns": ["meen 3ando khebra fel Python?"],
     "all_of": [AHMED], "sources": "some", "lang": "en"},
    {"id": "L4", "group": "Language", "turns": ["eh el email beta3 Ahmed Ramadan?"],
     "all_of": [["ahmedromo465"]], "sources": "some", "lang": "en"},
    {"id": "L5", "group": "Language", "turns": ["eh 3asemet faransa?"],
     "none_of": ["باريس", "paris"], "sources": "none", "lang": "en"},
    {"id": "L6", "group": "Language", "turns": ["meen el a7san?"],
     "clarify": True, "lang": "en"},
    {"id": "L7", "group": "Language", "turns": ["meen 3ando khebra fel Python?", "w eh el ta3leem beta3o?"],
     "sources": "some", "lang": "en"},
    {"id": "M1", "group": "Language", "turns": ["مين عنده experience في Deep Learning؟"],
     "all_of": [AHMED], "sources": "some", "lang": "mixed"},
    {"id": "M2", "group": "Language", "turns": ["ايه الـ skills بتاعة Ahmed Ramadan؟"],
     "sources": "some", "lang": "mixed"},
]