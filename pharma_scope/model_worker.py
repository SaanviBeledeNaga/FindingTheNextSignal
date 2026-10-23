"""One provider request per worker. Credentials stay in the inherited environment."""
import json
import sys

from .providers import Model, TransientModelError


def main():
    try:
        request = json.load(sys.stdin)
        model = Model(request['provider'], request['model'])
        result = model.generate(request['task'], request['schema'], request['data'], timeout=request['timeout'])
        response = {'result': result, 'usage': model.last_usage}
    except TransientModelError as exc:
        response = {'error': str(exc), 'transient': True, 'retry_after': exc.retry_after}
    except Exception as exc:
        # Never forward raw HTTP bodies, request headers, stack traces or arbitrary exception messages.
        response = {'error': f'Model request failed ({type(exc).__name__}); check model configuration or provider response.', 'transient': False}
    json.dump(response, sys.stdout)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
