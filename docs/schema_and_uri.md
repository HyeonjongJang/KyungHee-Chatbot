# KyungHee-Chatbot — URI 규칙 & 메타데이터 스키마 (v1.0)

## 1) 안정식 식별자(URN) 규칙
형태: `urn:khu:reg:{code}:{versionDate}:art{N}[:cl{M}]`
- `code`: 규정 식별자(예: AA)
- `versionDate`: 시행일(YYYY-MM-DD)
- `artN`: 제N조
- `clM`: (선택) N조의 제M항

예) `urn:khu:reg:AA:2024-09-01:art15:cl2`

## 2) 메타 스키마 (필드/타입)
```json
{
  "schema_version": "1.0",
  "uri": "string(URN)",
  "documentCode": "string",
  "versionDate": "YYYY-MM-DD",
  "effectiveFrom": "YYYY-MM-DD|null",
  "effectiveUntil": "YYYY-MM-DD|null",
  "contentType": "enum{text|table|annex}",
  "articleNumber": "int",
  "clauseNumber": "int|null",
  "program": "enum{UG,MS,PhD,IME_MS,...}",
  "cohort": "enum{Cohort_2022,Cohort_2023,...}",
  "sourceFile": "string(filename)",
  "page": "int|null",
  "md5": "string",
  "overrides": ["uri"] ,
  "cites": ["uri"],
  "hasExceptionFor": ["string|uri"]
}
