/**
 * つうがくナビ バックエンドの Worker ルーティング層。
 *
 * バックエンド本体(Python/FastAPI相当のraw HTTPサーバー、server.py)は
 * Cloudflare Containerとして動く。この Worker はリクエストをそのまま
 * コンテナに転送するだけの薄いプロキシで、アプリケーションロジック
 * (/ask, /score のハンドリング・CORS等)はserver.py側に残したまま。
 *
 * 単一のコンテナインスタンス(getContainerを名前無しで呼ぶと
 * "cf-singleton-container" という固定名になる)にルーティングする設計。
 * このバックエンドはリクエスト間で状態を持たないステートレスなAPIなので、
 * getByName(pathname)のようにパスごとに別インスタンスを立てる必要はない。
 */
import { Container, getContainer } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

export class BackendContainer extends Container {
  // server.py(旧hf_server.py)がPORT環境変数で待ち受けるポート。
  // Dockerfileの ENV PORT=8080 と一致させること。
  defaultPort = 8080;

  // 最後のリクエストからこの時間アクティビティが無ければコンテナを止める
  // (Cloudflare Containersは使った分だけ課金されるため、demoの合間は
  // 自動的にスケールダウンする)。
  sleepAfter = "10m";

  // Worker Secret(`wrangler secret put ANTHROPIC_API_KEY`で設定)を
  // コンテナ起動時の環境変数として渡す。/askエンドポイント
  // (lambda_handler.ask_ai_teacher)がClaude APIを呼ぶのに必要。
  // /scoreのみを使う場合はこの値が空でも動作する。
  envVars = {
    ANTHROPIC_API_KEY: env.ANTHROPIC_API_KEY ?? "",
  };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const container = getContainer(env.BACKEND);
    return container.fetch(request);
  },
};
