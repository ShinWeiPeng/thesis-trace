import { describe, expect, it } from "vitest";
import { generateClient, schemaType } from "./openapi-generator.mjs";

describe("OpenAPI schema generation", () => {
  it("never narrows unspecified values", () => {
    expect(schemaType()).toBe("unknown"); expect(schemaType({})).toBe("unknown");
    expect(schemaType({ type: "array", items: {} })).toBe("unknown[]");
  });
  it("emits OpenAPI const schemas as TypeScript literals", () => {
    expect(schemaType({ type: "string", const: "owner" })).toBe('"owner"');
    expect(schemaType({ const: false })).toBe("false");
  });
  it("recursively handles references, nullable and compositions", () => {
    expect(schemaType({ anyOf: [{ type: "string" }, { type: "integer" }], nullable: true })).toBe("(string | number) | null");
    expect(schemaType({ oneOf: [{ $ref: "#/components/schemas/A" }, { type: "null" }] })).toBe("A | null");
    expect(schemaType({ allOf: [{ $ref: "#/components/schemas/A" }, { type: "object", properties: { flag: { type: "boolean" } }, required: ["flag"] }] })).toBe("A & { \"flag\": boolean }");
  });
  it("handles typed and untyped additional properties", () => {
    expect(schemaType({ type: "object", additionalProperties: true })).toBe("Record<string, unknown>");
    expect(schemaType({ type: "object", additionalProperties: { type: "array", items: { $ref: "#/components/schemas/A" } } })).toBe("Record<string, never> & Record<string, A[]>");
  });
  it("uses unknown for an operation response without a schema", () => {
    const output = generateClient({ paths: { "/api/ping": { get: { operationId: "ping", responses: { 204: { description: "empty" } } } } } }, "fixture");
    expect(output).toContain("Promise<unknown>"); expect(output).toContain('OPENAPI_SHA256 = "fixture"');
  });
});
