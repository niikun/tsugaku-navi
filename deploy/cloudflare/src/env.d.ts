// `wrangler types`が生成するworker-configuration.d.ts(グローバルEnvインターフェース)に
// Secretsのフィールドをマージする。Secrets(`wrangler secret put`で設定)はwrangler.jsoncに
// 現れないため、自動生成の型には含まれない。宣言だけをここに手で足す。
interface Env {
  ANTHROPIC_API_KEY?: string;
}

// `import { env } from "cloudflare:workers"` (src/index.ts内)は名前空間付きの
// Cloudflare.Env型を使う。フラットな上のEnvとは別の宣言なので両方に足す必要がある。
declare namespace Cloudflare {
  interface Env {
    ANTHROPIC_API_KEY?: string;
  }
}
