const refName = (ref) => ref.split("/").at(-1);
const grouped = (value) => / [|&] /.test(value) ? `(${value})` : value;

export function schemaType(schema) {
  if (!schema || Object.keys(schema).length === 0) return "unknown";
  let value;
  if (Object.hasOwn(schema, "const")) value = JSON.stringify(schema.const);
  else if (schema.$ref) value = refName(schema.$ref);
  else if (schema.enum) value = schema.enum.map((item) => JSON.stringify(item)).join(" | ");
  else if (schema.anyOf) value = schema.anyOf.map(schemaType).join(" | ");
  else if (schema.oneOf) value = schema.oneOf.map(schemaType).join(" | ");
  else if (schema.allOf) value = schema.allOf.map(schemaType).join(" & ");
  else if (schema.type === "array") value = `${grouped(schemaType(schema.items))}[]`;
  else if (schema.type === "integer" || schema.type === "number") value = "number";
  else if (schema.type === "boolean") value = "boolean";
  else if (schema.type === "string") value = "string";
  else if (schema.type === "null") value = "null";
  else if (schema.type === "object" || schema.properties || schema.additionalProperties !== undefined) {
    const required = new Set(schema.required ?? []);
    const fields = Object.entries(schema.properties ?? {}).map(([name, field]) => `${JSON.stringify(name)}${required.has(name) ? "" : "?"}: ${schemaType(field)}`).join("; ");
    const object = fields ? `{ ${fields} }` : "Record<string, never>";
    if (schema.additionalProperties === true) value = fields ? `${object} & Record<string, unknown>` : "Record<string, unknown>";
    else if (typeof schema.additionalProperties === "object") value = `${object} & Record<string, ${schemaType(schema.additionalProperties)}>`;
    else value = object;
  } else value = "unknown";
  return schema.nullable && value !== "null" ? `${grouped(value)} | null` : value;
}

export function generateClient(document, hash) {
  const lines = ["/* eslint-disable */", "// Generated from backend OpenAPI. Do not edit.", `export const OPENAPI_SHA256 = "${hash}";`, ""];
  for (const [name, schema] of Object.entries(document.components?.schemas ?? {})) lines.push(`export type ${name} = ${schemaType(schema)};`, "");
  lines.push(`async function request<T>(fetcher: typeof fetch, url: string, init?: RequestInit): Promise<T> {\n  const response = await fetcher(url, { credentials: "same-origin", ...init });\n  if (!response.ok) throw response;\n  return (await response.json()) as T;\n}`, "");
  for (const [path, pathItem] of Object.entries(document.paths ?? {})) for (const [method, operation] of Object.entries(pathItem)) {
    if (!["get", "post", "put", "patch", "delete"].includes(method)) continue;
    const bodySchema = operation.requestBody?.content?.["application/json"]?.schema;
    const success = Object.entries(operation.responses ?? {}).find(([code]) => /^2/.test(code))?.[1];
    const responseSchema = success?.content?.["application/json"]?.schema;
    const pathParams = [...path.matchAll(/\{([^}]+)\}/g)].map((match) => match[1]);
    const params = ["baseUrl: string", ...pathParams.map((name) => `${name}: string`), ...(bodySchema ? [`body: ${schemaType(bodySchema)}`] : []), "fetcher: typeof fetch = fetch"];
    let url = path.replace(/^\/api/, "");
    for (const name of pathParams) url = url.replace(`{${name}}`, `\${encodeURIComponent(${name})}`);
    const init = method === "get" ? "" : `, { method: "${method.toUpperCase()}", headers: { "Content-Type": "application/json" }${bodySchema ? ", body: JSON.stringify(body)" : ""} }`;
    lines.push(`export function ${operation.operationId}(${params.join(", ")}): Promise<${schemaType(responseSchema)}> {`, `  return request(fetcher, \`\${baseUrl}${url}\`${init});`, "}", "");
  }
  return lines.join("\n");
}
