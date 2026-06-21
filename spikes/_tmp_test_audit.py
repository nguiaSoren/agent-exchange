import importlib.util, os, json
spec = importlib.util.spec_from_file_location("audit_contested", os.path.join(os.path.dirname(__file__), "audit_contested.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

report = json.load(open(m._REPORT))
corpus = m._load_corpus()
print("corpus contracts:", len(corpus))
contested = m._collect_contested(report, corpus)
print("contested:", len(contested))
matched = sum(1 for i in contested if i["doc_matched"])
print("matched to full:", matched, "fallback:", len(contested)-matched)
# show doc len distribution to confirm full text (not preview)
lens = sorted(set(len(i["_doc"]) for i in contested))
print("doc lengths (unique):", lens[:8])
# verify verdict normalize
for t in ["UNSUPPORTED", " supported.", "The claim is UNSUPPORTED", "maybe", None]:
    print(repr(t), "->", m._normalize_verdict(t))
# confirm cache_control + system shape builds w/o error for one payload (dry, no network)
it = contested[0]
print("sample custom_id:", it["custom_id"], "config:", it["config"])
print("claim[:80]:", it["claim"][:80])
