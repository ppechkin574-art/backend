import os

from quiz.dtos.enums import BlockType
from quiz.dtos.hint import HintServiceDTO
from quiz.dtos.text_blocks import TextBlockServiceDTO


def transform_video_hint(hint: HintServiceDTO | None) -> HintServiceDTO | None:
    if not hint:
        return None

    customer_code = os.getenv("CLOUDFLARE_CUSTOMER_CODE", "")
    if not customer_code:
        return hint

    transformed_blocks = []
    for block in hint.blocks:
        if block.type == BlockType.video:
            video_id = block.value
            if video_id:
                video_url = f"https://customer-{customer_code}.cloudflarestream.com/{video_id}/iframe"
                transformed_blocks.append(
                    TextBlockServiceDTO(id=block.id, order=block.order, type=block.type, value=video_url)
                )
            else:
                transformed_blocks.append(block)
        else:
            transformed_blocks.append(block)

    return HintServiceDTO(id=hint.id, blocks=transformed_blocks)
