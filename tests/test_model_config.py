from productivity_assistant.model_config import gemini_generate_content_config


def test_gemini_retries_transient_vertex_failures():
    config = gemini_generate_content_config()
    retry = config.http_options.retry_options

    assert retry.attempts == 5
    assert retry.initial_delay == 1.0
    assert retry.max_delay == 16.0
    assert retry.exp_base == 2.0
    assert retry.jitter == 1.0
    assert retry.http_status_codes == [429, 500, 502, 503, 504]


def test_each_agent_gets_an_independent_request_config():
    first = gemini_generate_content_config()
    second = gemini_generate_content_config()

    assert first is not second
    assert first.http_options is not second.http_options
    assert first.http_options.retry_options is not second.http_options.retry_options
