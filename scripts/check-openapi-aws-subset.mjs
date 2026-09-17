import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

export function validateOpenApiAwsSubset(source) {
  const failures = [];
  const expect = (condition, message) => {
    if (!condition) failures.push(message);
  };

  expect(
    /^openapi:\s*["']?3\.0\.3["']?\s*$/m.test(source),
    "OpenAPI version must be 3.0.3.",
  );

  const pathNames = [...source.matchAll(/^  (\/[^:\s]+):\s*$/gm)].map(
    (match) => match[1],
  );
  expect(
    pathNames.length === 1 && pathNames[0] === "/health",
    "Only GET /health may be declared.",
  );

  const operations = [...source.matchAll(/^    ([a-z]+):\s*$/gm)].map(
    (match) => match[1],
  );
  expect(
    operations.length === 1 && operations[0] === "get",
    "The sole route must define only GET.",
  );

  const forbiddenKeywords = [
    "nullable",
    "discriminator",
    "oneOf",
    "anyOf",
    "allOf",
    "not",
    "if",
    "then",
    "else",
    "const",
  ];
  for (const keyword of forbiddenKeywords) {
    expect(
      !new RegExp(`^\\s*${keyword}:`, "m").test(source),
      `API Gateway/SAM subset forbids '${keyword}'.`,
    );
  }

  const references = [...source.matchAll(/\$ref:\s*([^\s]+)/g)].map((match) =>
    match[1].replace(/["']/g, ""),
  );
  expect(
    references.every((reference) => reference.startsWith("#/")),
    "External $ref documents are not supported by the API Gateway/SAM subset.",
  );

  for (const name of [
    "OpaqueId",
    "UtcTimestamp",
    "CurrencyCode",
    "MoneyINR",
    "Version",
    "Revision",
    "JobStatus",
    "AsyncAccepted",
    "HealthSuccessResponse",
    "ErrorResponse",
  ]) {
    expect(
      new RegExp(`^    ${name}:`, "m").test(source),
      `Missing required component '${name}'.`,
    );
  }

  expect(
    /^    Idempotency-Key:/m.test(source),
    "Missing reusable Idempotency-Key header component.",
  );
  expect(
    /["']200["']:[\s\S]*HealthSuccessResponse/.test(source),
    "GET /health must have a concrete 200 response.",
  );
  expect(
    /["']500["']:[\s\S]*ErrorResponse/.test(source),
    "GET /health must have a concrete 500 response.",
  );

  return failures;
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const contractPath = process.argv[2];
  if (!contractPath) {
    throw new Error("Usage: node check-openapi-aws-subset.mjs <openapi.yaml>");
  }
  const source = await readFile(resolve(contractPath), "utf8");
  const failures = validateOpenApiAwsSubset(source);
  if (failures.length > 0) {
    throw new Error(
      `OpenAPI AWS-subset validation failed:\n- ${failures.join("\n- ")}`,
    );
  }
  console.log("OpenAPI documented AWS/SAM subset validation passed.");
}
