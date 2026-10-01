import time
import psutil
from llama_cpp import Llama

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
# Point this to your locally downloaded GGUF model file
MODEL_PATH = "./models/qwen1_5-1_8b-chat-q4_k_m.gguf" 
PROMPT = "Explain the fundamental difference between TCP and UDP protocols in one short paragraph."

def main():
    print("Loading model...")
    # Initialize the model. 
    # n_gpu_layers=0 forces CPU-only execution for baseline testing across Windows/macOS.
    # Set n_gpu_layers=-1 if you want to test Metal (macOS) acceleration.
    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=2048,
        n_gpu_layers=0, 
        verbose=False # Set to False to keep our telemetry output clean
    )
    
    print("\nStarting inference benchmark...")
    
    # ---------------------------------------------------------
    # Baseline Telemetry Snapshot
    # ---------------------------------------------------------
    process = psutil.Process()
    # Call cpu_percent once to initialize the baseline measurement
    process.cpu_percent()
    
    baseline_ram_mb = process.memory_info().rss / (1024 * 1024)
    print(f"Baseline RAM utilization: {baseline_ram_mb:.2f} MB")
    
    # ---------------------------------------------------------
    # Inference & Timing Execution
    # ---------------------------------------------------------
    print("\nPrompt Output:")
    print("-" * 50)
    
    start_time = time.perf_counter()
    first_token_time = None
    token_count = 0
    
    # We use streaming to capture the exact moment the first token arrives (TTFT)
    stream = llm(
        PROMPT,
        max_tokens=256,
        stream=True
    )
    
    for output in stream:
        # Capture Time to First Token (TTFT) on the first iteration
        if first_token_time is None:
            first_token_time = time.perf_counter()
            ttft_ms = (first_token_time - start_time) * 1000
        
        token = output["choices"][0]["text"]
        print(token, end="", flush=True)
        token_count += 1
        
    end_time = time.perf_counter()
    print("\n" + "-" * 50)
    
    # ---------------------------------------------------------
    # Final Telemetry Calculations
    # ---------------------------------------------------------
    # Calculate process-level CPU and RAM during the generation window
    avg_cpu_percent = process.cpu_percent()
    peak_ram_mb = process.memory_info().rss / (1024 * 1024)
    
    # Calculate Tokens Per Second (TPS)
    # We measure TPS from the first token to the end, excluding the prompt processing (prefill) time
    generation_duration = end_time - first_token_time
    tps = (token_count - 1) / generation_duration if generation_duration > 0 else 0
    
    print("\n--- Operational Telemetry Results ---")
    print(f"Time to First Token (TTFT): {ttft_ms:.2f} ms")
    print(f"Tokens Per Second (TPS):    {tps:.2f} tokens/sec")
    print(f"Process CPU Utilization:    {avg_cpu_percent:.2f}% (over {psutil.cpu_count(logical=True)} logical cores)")
    print(f"Process Peak RAM usage:     {peak_ram_mb:.2f} MB")
    print("-" * 37)

if __name__ == "__main__":
    main()