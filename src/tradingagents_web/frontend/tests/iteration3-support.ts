import { existsSync } from "node:fs";

export function requireImplemented(relativePath: string): void {
  if (!existsSync(relativePath)) {
    throw new Error(
      `EXPECTED-UNIMPLEMENTED: ${relativePath} is not implemented yet`,
    );
  }
}

export function unimplemented(relativePath: string): never {
  throw new Error(
    `EXPECTED-UNIMPLEMENTED: ${relativePath} is not implemented yet`,
  );
}
