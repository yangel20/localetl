# Wave 0 consistency check across contracts/, docs/ and .claude/agents/.
# Dev-only deps: pip install jsonschema==4.23.0 pyyaml==6.0.2 openapi-spec-validator==0.7.1
# Usage: python contracts/tools/check_contracts.py .
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

root = Path(sys.argv[1])
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


schema_path = root / "contracts/pipeline.schema.json"
schema = json.loads(schema_path.read_text())
Draft202012Validator.check_schema(schema)
check(True, "pipeline.schema.json is a valid draft 2020-12 schema")
validator = Draft202012Validator(schema)

for f in sorted((root / "contracts/examples/pipeline/valid").glob("*.json")):
    errs = list(validator.iter_errors(json.loads(f.read_text())))
    check(not errs, f"valid example accepted: {f.name}" + (f" -> {errs[0].message}" if errs else ""))
for f in sorted((root / "contracts/examples/pipeline/invalid").glob("*.json")):
    errs = list(validator.iter_errors(json.loads(f.read_text())))
    check(bool(errs), f"invalid example rejected: {f.name}")

spec_dict, base_uri = read_from_filename(str(root / "contracts/openapi.yaml"))
validate(spec_dict, base_uri=base_uri)
check(True, "openapi.yaml is valid OpenAPI 3.1 (external refs resolved)")
spec = yaml.safe_load((root / "contracts/openapi.yaml").read_text())
S = spec["components"]["schemas"]
D = schema["$defs"]

# every internal $ref resolves
text = (root / "contracts/openapi.yaml").read_text()
for ref in sorted(set(re.findall(r"#/components/(\w+)/(\w+)", text))):
    check(ref[1] in spec["components"].get(ref[0], {}), f"ref resolves: #/components/{ref[0]}/{ref[1]}")
for ref in sorted(set(re.findall(r"pipeline\.schema\.json#/\$defs/(\w+)", text))):
    check(ref in D, f"external ref resolves: pipeline.schema.json#/$defs/{ref}")

arch = (root / "docs/architecture.md").read_text()
req = (root / "docs/requirements.md").read_text()

run_status = S["RunStatus"]["enum"]
check(run_status == ["queued", "running", "succeeded", "failed", "interrupted"], "RunStatus enum is the agreed 5 states")
check(sorted(S["MetricsSummary"]["properties"]["runs_by_status"]["required"]) == sorted(run_status), "MetricsSummary.runs_by_status keys == RunStatus")
check("`queued`, `running`, `succeeded`, `failed`, `interrupted`" in arch, "architecture run_status enum == RunStatus")
check("`queued`, `running`, `succeeded`, `failed`, `interrupted`" in req, "requirements run states == RunStatus")

stages = S["Stage"]["enum"]
check(f'Stage = Literal[{", ".join(repr(s).replace(chr(39), chr(34)) for s in stages)}]' in arch, "architecture Stage literal == OpenAPI Stage")
check(all(f"`{s}`" in req for s in stages), "requirements list every stage")

event_status = S["RunEvent"]["properties"]["status"]["enum"]
check(f'EventStatus = Literal[{", ".join(chr(34)+s+chr(34) for s in event_status)}]' in arch, "architecture EventStatus == RunEvent.status")

col_types = D["ColumnType"]["enum"]
check(f'ColumnType = Literal[{", ".join(chr(34)+t+chr(34) for t in col_types)}]' in arch, "architecture ColumnType == schema ColumnType")
check(all(f"| {t} |" in arch for t in col_types), "every ColumnType has a PostgreSQL mapping")

ops = D["Transformation"]["properties"]["op"]["enum"]
op_consts = sorted(D[r["$ref"].split("/")[-1]]["properties"]["op"]["const"] for r in D["Transformation"]["oneOf"])
check(sorted(ops) == op_consts, "transformation op enum == oneOf branch consts")
check(all(f"`{o}`" in req for o in ops), "requirements list every transformation op")

rules = D["Validation"]["properties"]["rule"]["enum"]
rule_consts = sorted(D[r["$ref"].split("/")[-1]]["properties"]["rule"]["const"] for r in D["Validation"]["oneOf"])
check(sorted(rules) == rule_consts, "validation rule enum == oneOf branch consts")
check(all(f"`{r}`" in req for r in rules), "requirements list every validation rule")
rej = S["RejectedRow"]["properties"]["rule"]["enum"]
check(rej == rules + ["type_cast", "parse_error"], "RejectedRow.rule == validation rules + type_cast, parse_error")
check(f'RejectionRule = Literal[{", ".join(chr(34)+r+chr(34) for r in rej)}]' in arch, "architecture RejectionRule == RejectedRow.rule")

csv = D["CsvOptions"]["properties"]
up = S["SourceUpload"]["properties"]
for k in ("encoding", "delimiter"):
    check(csv[k]["enum"] == up[k]["enum"], f"SourceUpload.{k} enum == CsvOptions.{k}")
    check(csv[k]["default"] == up[k]["default"], f"SourceUpload.{k} default == CsvOptions.{k}")
check(csv["quote_char"]["default"] == up["quote_char"]["default"], "quote_char default matches")
check('encoding: Literal["utf-8", "utf-8-sig", "latin-1", "cp1252"] = "utf-8"' in arch, "architecture CsvOptions.encoding matches schema")

ident = D["Identifier"]["pattern"]
check(ident in req, "identifier pattern stated in requirements matches schema")

limits = spec["components"]["parameters"]["Limit"]["schema"]
check(limits["maximum"] == 200, "page limit max 200")
prev = spec["paths"]["/sources/{source_id}/preview"]["get"]["parameters"][0]["schema"]
check(prev["default"] == 50 and prev["maximum"] == 500, "preview limit default 50 / max 500 matches REQ-05")

# every operation: unique operationId, every non-2xx uses Error
ops_ids = []
for path, item in spec["paths"].items():
    for method, op in item.items():
        if method == "parameters":
            continue
        ops_ids.append(op["operationId"])
        for code, resp in op["responses"].items():
            if not code.startswith("2"):
                check("$ref" in resp and resp["$ref"].startswith("#/components/responses/"), f"{method.upper()} {path} {code} uses shared Error response")
check(len(ops_ids) == len(set(ops_ids)), f"{len(ops_ids)} unique operationIds")

# Run.required covers all properties
for name in ("Run", "Pipeline", "Dataset", "RunEvent", "RejectedRow", "ColumnProfile", "DataSource"):
    sch = S[name]
    check(set(sch["required"]) == set(sch["properties"]), f"{name}: every property is required (nullable via type)")

# ownership: every directory in agents' files appears in the architecture table
for agent in sorted((root / ".claude/agents").glob("*.md")):
    body = agent.read_text()
    check(body.startswith("---\n"), f"{agent.name}: frontmatter on line 1")
    owned = re.findall(r"^- ((?:backend|frontend|tests|scripts|docs|\.github)[\w/.\-]*/)\s*$", body, re.M)
    for d in owned:
        check(f"`{d}`" in arch, f"{agent.name}: owned path {d} is in architecture ownership table")

# no stray keys inside schema objects (catches YAML flow-mapping comma bugs)
KW = {"type","format","enum","const","minimum","maximum","minLength","maxLength","minItems","maxItems","uniqueItems",
      "items","properties","required","additionalProperties","allOf","oneOf","anyOf","$ref","description","default",
      "contentMediaType","pattern","minProperties","maxProperties","title","$schema","$id","$defs"}
def walk(node, ptr):
    if isinstance(node, dict):
        is_schema = any(k in node for k in ("type","$ref","enum","const","oneOf","allOf","anyOf","properties"))
        if is_schema:
            bad = set(node) - KW
            check(not bad, f"no unknown keywords at {ptr}" + (f": {sorted(bad)}" if bad else "")) if bad else None
        for k, v in node.items():
            if k in ("properties", "$defs", "schemas"):
                for name, sub in v.items():
                    walk(sub, f"{ptr}/{k}/{name}")
            elif isinstance(v, (dict, list)):
                walk(v, f"{ptr}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, f"{ptr}/{i}")
before = len(failures)
walk(spec, "openapi"); walk(schema, "pipeline")
check(len(failures) == before, "no unknown keywords in any schema object (openapi + pipeline)")

# Q3 row outcome accounting: same five counters in the HTTP contract and the engine interface
COUNTERS = ["extracted_count", "loaded_count", "rejected_count", "duplicate_dropped_count", "null_dropped_count"]
run_props = S["Run"]["properties"]
check(all(c in run_props and c in S["Run"]["required"] for c in COUNTERS), "Run exposes all five Q3 row counters (required)")
rr = arch.split("class RunResult:")[1].split("rejected_sample")[0]
check(re.findall(r"^\s+(\w+): int", rr, re.M) == COUNTERS, "architecture RunResult counters == Run counters, same order")
rc = arch.split("class RunCounters:")[1].split("@dataclass")[0]
check(re.findall(r"^\s+(\w+): int", rc, re.M) == COUNTERS, "architecture RunCounters == Run counters, same order")
check("counters: RunCounters" in arch.split("class StageEvent:")[1].split("@dataclass")[0], "StageEvent carries cumulative RunCounters")
check("extracted_count = loaded_count + rejected_count + duplicate_dropped_count + null_dropped_count" in arch, "reconciliation identity stated in architecture")
check("loaded_count" in S["MetricsSummary"]["properties"]["daily"]["items"]["required"], "MetricsSummary.daily uses loaded_count")
legacy = re.compile(r"\brows_(read|rejected|loaded)\b|rows_loaded_total")
for f in ("contracts/openapi.yaml", "contracts/pipeline.schema.json", "docs/architecture.md", "docs/requirements.md"):
    hits = [i + 1 for i, line in enumerate((root / f).read_text().splitlines()) if legacy.search(line)]
    check(not hits, f"no legacy row counter names in {f}" + (f" (lines {hits})" if hits else ""))

print()
print(f"{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
