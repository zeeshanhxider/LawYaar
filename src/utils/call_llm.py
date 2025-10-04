from openai import OpenAI, AsyncOpenAI
import os
from dotenv import load_dotenv
import asyncio
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_llm_config

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Global variable to store current LLM configuration
_current_llm_config = {
    "provider": None,
    "model": None
}

# Thread-safe storage for token usage tracking
import threading
_usage_lock = threading.Lock()
_token_usage = {
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "total_tokens": 0,
    "calls_by_model": {}
}

# OpenAI pricing per 1M tokens (as of January 2025)
OPENAI_PRICING = {
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4-turbo": {"prompt": 10.00, "completion": 30.00},
    "gpt-4": {"prompt": 30.00, "completion": 60.00},
    "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
    "o1": {"prompt": 15.00, "completion": 60.00},
    "o1-mini": {"prompt": 3.00, "completion": 12.00},
}

GEMINI_PRICING = {
    "gemini-2.0-flash": {"prompt": 0.10, "completion": 0.40},     # Includes gemini-2.0-flash-exp
    "gemini-2.5-flash": {"prompt": 0.10, "completion": 0.40},     # Includes gemini-2.5-flash-preview
    "gemini-1.5-flash": {"prompt": 0.075, "completion": 0.30},    # Includes gemini-1.5-flash-002, -8b, -exp
    "gemini-1.5-pro": {"prompt": 1.25, "completion": 5.00},       # Includes gemini-1.5-pro-002, -exp
    "gemini-1.0-pro": {"prompt": 0.50, "completion": 1.50},       # Includes gemini-1.0-pro-002
    "gemini-pro": {"prompt": 0.50, "completion": 1.50},           # Legacy naming
}

def reset_usage_tracking():
    """Reset usage tracking for a new session"""
    global _token_usage
    with _usage_lock:
        _token_usage = {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "calls_by_model": {}
        }

def _track_usage(model: str, prompt_tokens: int, completion_tokens: int):
    """Track token usage for cost calculation"""
    global _token_usage
    with _usage_lock:
        _token_usage["total_prompt_tokens"] += prompt_tokens
        _token_usage["total_completion_tokens"] += completion_tokens
        _token_usage["total_tokens"] += (prompt_tokens + completion_tokens)
        
        if model not in _token_usage["calls_by_model"]:
            _token_usage["calls_by_model"][model] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "call_count": 0
            }
        
        _token_usage["calls_by_model"][model]["prompt_tokens"] += prompt_tokens
        _token_usage["calls_by_model"][model]["completion_tokens"] += completion_tokens
        _token_usage["calls_by_model"][model]["total_tokens"] += (prompt_tokens + completion_tokens)
        _token_usage["calls_by_model"][model]["call_count"] += 1

def get_usage_and_cost():
    """Get current usage statistics and calculated cost (provider-agnostic)"""
    global _token_usage
    import logging
    logger = logging.getLogger(__name__)
    
    with _usage_lock:
        total_cost = 0.0
        model_costs = {}
        detected_provider = None
        
        for model, usage in _token_usage["calls_by_model"].items():
            # Find matching pricing (handle model variations)
            pricing = None
            provider = None
            model_lower = model.lower()
            
            # Try OpenAI pricing first
            # Sort by length descending to match longer/more specific names first
            for price_key in sorted(OPENAI_PRICING.keys(), key=len, reverse=True):
                if price_key in model_lower:
                    pricing = OPENAI_PRICING[price_key]
                    provider = "openai"
                    logger.debug(f"Matched OpenAI model '{model}' to pricing key '{price_key}'")
                    break
            
            # If not found, try Gemini pricing
            if not pricing:
                for price_key in sorted(GEMINI_PRICING.keys(), key=len, reverse=True):
                    if price_key in model_lower:
                        pricing = GEMINI_PRICING[price_key]
                        provider = "gemini"
                        logger.debug(f"Matched Gemini model '{model}' to pricing key '{price_key}'")
                        break
            
            if pricing:
                if not detected_provider:
                    detected_provider = provider
                    
                prompt_cost = (usage["prompt_tokens"] / 1_000_000) * pricing["prompt"]
                completion_cost = (usage["completion_tokens"] / 1_000_000) * pricing["completion"]
                model_cost = prompt_cost + completion_cost
                total_cost += model_cost
                
                model_costs[model] = {
                    "prompt_tokens": usage["prompt_tokens"],
                    "completion_tokens": usage["completion_tokens"],
                    "total_tokens": usage["total_tokens"],
                    "call_count": usage["call_count"],
                    "prompt_cost": round(prompt_cost, 4),
                    "completion_cost": round(completion_cost, 4),
                    "total_cost": round(model_cost, 4)
                }
            else:
                logger.warning(f"No pricing found for model: {model}")
        
        logger.info(f"Cost calculation complete: ${total_cost:.4f} for {len(model_costs)} model(s)")
        
        return {
            "total_prompt_tokens": _token_usage["total_prompt_tokens"],
            "total_completion_tokens": _token_usage["total_completion_tokens"],
            "total_tokens": _token_usage["total_tokens"],
            "total_cost": round(total_cost, 4),
            "models": model_costs,
            "provider": detected_provider or "unknown"
        }

def set_llm_config(provider: str, model: str):
    """Set the LLM provider and model to use for subsequent calls"""
    global _current_llm_config
    _current_llm_config["provider"] = provider
    _current_llm_config["model"] = model

def get_current_llm_config():
    """Get the current LLM configuration, falling back to settings if not set"""
    global _current_llm_config
    config = get_llm_config()
    
    return {
        "provider": _current_llm_config["provider"] or config.PROVIDER,
        "model": _current_llm_config["model"] or config.MODEL
    }

def call_llm(prompt):
    """Call LLM with dynamic provider and model selection"""
    current_config = get_current_llm_config()
    provider = current_config["provider"]
    model = current_config["model"]
    
    if provider == "openai":
        return _call_openai(prompt, model)
    elif provider == "gemini":
        return _call_gemini(prompt, model)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

async def call_llm_async(prompt):
    """Async version of call_llm for true parallel execution"""
    current_config = get_current_llm_config()
    provider = current_config["provider"]
    model = current_config["model"]
    
    if provider == "openai":
        return await _call_openai_async(prompt, model)
    elif provider == "gemini":
        return await _call_gemini_async(prompt, model)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

def _call_openai(prompt, model):
    """Call OpenAI API"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables. Please check your .env file.")
    
    client = OpenAI(api_key=api_key)
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    
    # Track usage if available
    if hasattr(r, 'usage') and r.usage:
        _track_usage(model, r.usage.prompt_tokens, r.usage.completion_tokens)
    
    return r.choices[0].message.content

async def _call_openai_async(prompt, model):
    """Call OpenAI API asynchronously"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables. Please check your .env file.")
    
    client = AsyncOpenAI(api_key=api_key)
    r = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    
    # Track usage if available
    if hasattr(r, 'usage') and r.usage:
        _track_usage(model, r.usage.prompt_tokens, r.usage.completion_tokens)
    
    return r.choices[0].message.content

def _call_gemini(prompt, model):
    """Call Gemini API"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables. Please check your .env file.")
    
    from google import genai
    import logging
    logger = logging.getLogger(__name__)
    
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt
    )
    
    # Track usage if available (Gemini uses usage_metadata)
    try:
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            # Try different possible attribute names
            prompt_tokens = (
                getattr(response.usage_metadata, 'prompt_token_count', None) or
                getattr(response.usage_metadata, 'promptTokenCount', None) or 0
            )
            completion_tokens = (
                getattr(response.usage_metadata, 'candidates_token_count', None) or
                getattr(response.usage_metadata, 'candidatesTokenCount', None) or 0
            )
            
            if prompt_tokens or completion_tokens:
                _track_usage(model, prompt_tokens, completion_tokens)
                logger.debug(f"Gemini usage tracked: {prompt_tokens} prompt + {completion_tokens} completion tokens")
            else:
                logger.warning(f"Gemini response has usage_metadata but no token counts found")
        else:
            logger.warning(f"Gemini response missing usage_metadata")
    except Exception as e:
        logger.error(f"Error tracking Gemini usage: {e}")
    
    return response.text

async def _call_gemini_async(prompt, model):
    """Call Gemini API asynchronously using streaming for true async"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables. Please check your .env file.")
    
    from google import genai
    import concurrent.futures
    import logging
    logger = logging.getLogger(__name__)
    
    # Use streaming for true async operation
    # Gemini's stream_generate_content provides Server-Sent Events (SSE) for async experience
    def _stream_call():
        client = genai.Client(api_key=api_key)
        # Use streaming to get chunks asynchronously
        response_stream = client.models.generate_content_stream(
            model=model,
            contents=prompt
        )
        
        # Collect all chunks from the stream
        full_text = []
        last_chunk = None
        for chunk in response_stream:
            if chunk.text:
                full_text.append(chunk.text)
            last_chunk = chunk
        
        # Track usage from the last chunk if available
        try:
            if last_chunk and hasattr(last_chunk, 'usage_metadata') and last_chunk.usage_metadata:
                # Try different possible attribute names
                prompt_tokens = (
                    getattr(last_chunk.usage_metadata, 'prompt_token_count', None) or
                    getattr(last_chunk.usage_metadata, 'promptTokenCount', None) or 0
                )
                completion_tokens = (
                    getattr(last_chunk.usage_metadata, 'candidates_token_count', None) or
                    getattr(last_chunk.usage_metadata, 'candidatesTokenCount', None) or 0
                )
                
                if prompt_tokens or completion_tokens:
                    _track_usage(model, prompt_tokens, completion_tokens)
                    logger.debug(f"Gemini async usage tracked: {prompt_tokens} prompt + {completion_tokens} completion tokens")
        except Exception as e:
            logger.error(f"Error tracking Gemini async usage: {e}")
        
        return ''.join(full_text)
    
    # Run the streaming call in a thread pool to avoid blocking
    # This allows multiple concurrent Gemini calls to process in parallel
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _stream_call)
    
    return result
    
if __name__ == "__main__":
    prompt = "What is the meaning of life?"
    print(call_llm(prompt))
