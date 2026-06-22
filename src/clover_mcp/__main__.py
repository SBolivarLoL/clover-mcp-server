from clover_mcp.config import load_config
from clover_mcp.server import mcp


def main() -> None:
    config = load_config()
    if config.transport == "http":
        # Remote/hosted mode. Auth is enforced by the provider wired at server
        # construction (build_auth_provider refuses http without an IdP).
        mcp.run(
            transport="http",
            host=config.http_host,
            port=config.http_port,
            path=config.http_path,
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
