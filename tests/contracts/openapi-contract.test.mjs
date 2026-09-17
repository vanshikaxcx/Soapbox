import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { resolve } from "node:path";

import { validateOpenApiAwsSubset } from "../../scripts/check-openapi-aws-subset.mjs";

const contractPath = resolve(
  import.meta.dirname,
  "../../contracts/openapi.yaml",
);
const source = await readFile(contractPath, "utf8");

function component(name) {
  const start = source.indexOf(`    ${name}:`);
  assert.notEqual(start, -1, `missing component ${name}`);
  const remainder = source.slice(start + 1);
  const next = remainder.search(/\n {4}\S/);
  return source.slice(start, next === -1 ? source.length : start + 1 + next);
}

test("contract uses the documented AWS/SAM-compatible route subset", () => {
  assert.deepEqual(validateOpenApiAwsSubset(source), []);
  assert.match(source, /^openapi: 3\.0\.3$/m);
  assert.match(source, /^  \/health:\n    get:/m);
});

test("subset validation rejects future routes, methods, external refs, and unsupported composition", () => {
  assert.ok(validateOpenApiAwsSubset(`${source}\n  /future:\n`).length > 0);
  assert.ok(
    validateOpenApiAwsSubset(source.replace("    get:", "    post:")).length >
      0,
  );
  assert.ok(
    validateOpenApiAwsSubset(
      source.replace(
        "#/components/schemas/HealthData",
        "other.yaml#/HealthData",
      ),
    ).length > 0,
  );
  assert.ok(validateOpenApiAwsSubset(`${source}\n    oneOf: []\n`).length > 0);
});

test("approved opaque, timestamp, currency, money, and counter primitives remain constrained", () => {
  assert.match(component("OpaqueId"), /type: string[\s\S]*minLength: 1/);
  assert.match(
    component("UtcTimestamp"),
    /type: string[\s\S]*format: date-time/,
  );
  assert.match(component("CurrencyCode"), /enum:\s*\n\s*- INR/);
  assert.match(
    component("MoneyINR"),
    /amount_paise:[\s\S]*minimum: 0[\s\S]*maximum: 9007199254740991/,
  );
  assert.match(
    component("MoneyINR"),
    /currency:[\s\S]*#\/components\/schemas\/CurrencyCode/,
  );
  for (const name of ["Version", "Revision"]) {
    assert.match(
      component(name),
      /type: integer[\s\S]*minimum: 0[\s\S]*maximum: 9007199254740991/,
    );
  }
});

test("approved idempotency and asynchronous transport primitives remain exact", () => {
  assert.match(
    source,
    /Idempotency-Key:[\s\S]*in: header[\s\S]*required: true[\s\S]*minLength: 1/,
  );
  assert.match(
    component("JobStatus"),
    /- queued[\s\S]*- running[\s\S]*- succeeded[\s\S]*- failed/,
  );
  assert.match(
    component("AsyncAccepted"),
    /required:[\s\S]*- job_id[\s\S]*- resource_id[\s\S]*- status_url/,
  );
});

test("health responses use concrete success and safe error envelopes with request IDs", () => {
  assert.match(
    source,
    /["']200["']:[\s\S]*#\/components\/schemas\/HealthSuccessResponse/,
  );
  assert.match(
    source,
    /["']500["']:[\s\S]*#\/components\/schemas\/ErrorResponse/,
  );
  assert.match(
    component("HealthSuccessResponse"),
    /data:[\s\S]*HealthData[\s\S]*request_id:[\s\S]*OpaqueId/,
  );
  assert.match(
    component("ErrorBody"),
    /required:[\s\S]*- code[\s\S]*- message[\s\S]*- details/,
  );
  assert.match(
    component("ErrorResponse"),
    /error:[\s\S]*ErrorBody[\s\S]*request_id:[\s\S]*OpaqueId/,
  );
});
