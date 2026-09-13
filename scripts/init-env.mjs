// Create .env from .env.example if missing, and fill secrets that must not be blank.
// Never overwrites a value that is already set.
import { existsSync, readFileSync, writeFileSync, copyFileSync } from "node:fs";
import { randomBytes } from "node:crypto";

const ENV = ".env";
if (!existsSync(ENV)) {
  copyFileSync(".env.example", ENV);
  console.log("created .env from .env.example");
}

const generators = {
  // Fernet key: urlsafe base64 of 32 random bytes.
  VAULT_MASTER_KEY: () => randomBytes(32).toString("base64url") + "=",
  INBOUND_WEBHOOK_SECRET: () => randomBytes(32).toString("hex"),
};

let text = readFileSync(ENV, "utf8");
for (const [key, make] of Object.entries(generators)) {
  const re = new RegExp(`^${key}=(.*)$`, "m");
  const m = text.match(re);
  if (!m) {
    text += `${text.endsWith("\n") ? "" : "\n"}${key}=${make()}\n`;
    console.log(`added ${key}`);
  } else if (!m[1].trim() || m[1].trim().startsWith("replace-with")) {
    text = text.replace(re, `${key}=${make()}`);
    console.log(`generated ${key}`);
  }
}
writeFileSync(ENV, text);
console.log("Add your provider API keys to .env (see the provider section), then run: npm start");
