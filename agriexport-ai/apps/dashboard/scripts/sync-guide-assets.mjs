import { existsSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
const available = Object.fromEntries(["truck", "container", "crane"].map(name => [name, existsSync(resolve(`public/guide/${name}.webp`))]));
writeFileSync(resolve("public/guide/assets.json"), JSON.stringify(available) + "\n");
console.log("Guide assets:", Object.entries(available).map(([name, found]) => `${name}=${found ? "supplied" : "TODO placeholder"}`).join(", "));
