import logging

logger = logging.getLogger(__name__)

try:
    from pocketflow import Flow, AsyncFlow
    from nodes import DocumentIngestionNode, VectorIndexCreationNode, InitialRetrievalNode, DocumentExtractionNode
    from nodes_agents import DocumentProcessorNode, ResponseComposerNode
    HAS_POCKETFLOW = True
except Exception as e:
    # Fallback stubs so the module can be imported even when pocketflow is not installed.
    HAS_POCKETFLOW = False
    logger.warning(f"pocketflow or nodes modules not available: {e}")

    class Flow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            raise RuntimeError("pocketflow is not installed; install it or provide a compatible Flow implementation")

    class AsyncFlow:
        def __init__(self, *args, **kwargs):
            pass

        async def run_async(self, *args, **kwargs):
            raise RuntimeError("pocketflow is not installed; install it or provide a compatible AsyncFlow implementation")


def create_offline_indexing_flow():
    """Create offline flow for document ingestion and vector database creation.

    If `pocketflow` is not installed, returns a stub Flow object whose `run`
    method will raise an informative RuntimeError when invoked.
    """
    if not HAS_POCKETFLOW:
        logger.warning("Returning stub offline flow because pocketflow is missing")
        return Flow()

    # Create nodes
    ingestion_node = DocumentIngestionNode()
    indexing_node = VectorIndexCreationNode()

    # Connect nodes in sequence
    ingestion_node >> indexing_node

    # Create flow starting with ingestion
    flow = Flow(start=ingestion_node)
    logger.info("Created offline indexing flow")
    return flow


def create_online_research_flow():
    """Create online flow for query processing and research.

    If `pocketflow` is not installed, returns a stub AsyncFlow object whose
    `run_async` method will raise an informative RuntimeError when invoked.
    """
    if not HAS_POCKETFLOW:
        logger.warning("Returning stub online flow because pocketflow is missing")
        return AsyncFlow()

    # Create nodes
    retrieval_node = InitialRetrievalNode()
    extraction_node = DocumentExtractionNode()
    processor_node = DocumentProcessorNode()
    composer_node = ResponseComposerNode()

    # Connect nodes in sequence - minimal pipeline
    retrieval_node >> extraction_node >> processor_node >> composer_node

    # Create async flow (required for parallel processing nodes)
    flow = AsyncFlow(start=retrieval_node)
    logger.info("Created online research flow")
    return flow


def create_complete_legal_ai_system():
    """Create complete legal AI system with both offline and online components.

    Returns:
        Tuple of (offline_flow, online_flow)
    """
    offline_flow = create_offline_indexing_flow()
    online_flow = create_online_research_flow()
    logger.info("Created complete legal AI system")
    return offline_flow, online_flow


# Create flows for easy import (these may be stubs if pocketflow is missing)
offline_flow = create_offline_indexing_flow()
online_flow = create_online_research_flow()