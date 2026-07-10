Fixed a display freeze under the Electron binary pixel transport: the routing
layer stripped the pixel key out of the slimmed geom JSON, so the renderer's
"unchanged → skip re-upload" caches (Canvas2D blit cache, WebGPU texture,
overlay-mask cache) fell back to a 4-sampled-byte fingerprint of the buffer —
two frames differing anywhere else collided and the display stayed frozen on
the old frame (seen as a stale overview after a movie scrub). The slimmed geom
now carries a small ``\x00bin:<checksum>`` content token under the pixel key,
binary buffers are additionally stamped with an arrival sequence as a fallback
key, and the overlay-mask draw path now reads the binary byte side-channel
(it previously only decoded base64, so masks never displayed over the binary
transport).
