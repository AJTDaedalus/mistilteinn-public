/**
 * The GPU backend: the same damage chain, as a WGSL compute shader.
 *
 * `damage.ts` is the CPU backend and computes through `Math.fround` precisely so the two
 * agree — see its header. This one is where that precision actually comes from.
 *
 * ## Why the interface takes a batch
 *
 * Each combination in a five-slot product is independent, so the search is embarrassingly
 * parallel. That is the whole reason a GPU is worth reaching for (DESIGN §2), and it is why
 * this exposes `computeDamageBatch` rather than a per-hit call: a GPU dispatched once per hit
 * would be slower than the CPU, not faster.
 */

/** Field count per case. 16 rather than 15 so cases start on 64-byte boundaries. */
export const CASE_STRIDE = 16;

/** Byte offsets into a case, in `Float32Array` element indices. Mirrors `Case` in the WGSL. */
export const FIELD = {
  multiplier: 0,
  scalingValue: 1,
  dmgBonus: 2,
  critRate: 3,
  critDmg: 4,
  elementalMastery: 5,
  characterLevel: 6,
  enemyLevel: 7,
  resistance: 8,
  defReduction: 9,
  defIgnore: 10,
  flatDamage: 11,
  baseDamageBonus: 12,
  /** The reaction's own multiplier, or 0 for none. See the WGSL on why not an enum. */
  amplifyingMultiplier: 13,
  reactionBonus: 14,
} as const;

/** `GPUBufferUsage` / `GPUMapMode` are not globals outside a browser, so the spec values. */
const USAGE_STORAGE = 0x80;
const USAGE_COPY_SRC = 0x04;
const USAGE_COPY_DST = 0x08;
const USAGE_MAP_READ = 0x01;
const MAP_READ = 0x1;

const WORKGROUP_SIZE = 64;

export interface GpuKernel {
  /** One damage figure per case, in input order. */
  /**
   * `Float32Array<ArrayBuffer>`, not the default `ArrayBufferLike`: WebGPU's `writeBuffer`
   * will not take a `SharedArrayBuffer`-backed view, and the distinction is worth keeping in
   * the signature rather than casting it away at the call site.
   */
  computeDamageBatch(cases: Float32Array<ArrayBuffer>): Promise<Float32Array>;
  destroy(): void;
}

/**
 * Build a kernel on an existing device.
 *
 * `tick` exists because Node's WebGPU bindings do not pump Dawn's event loop themselves:
 * `mapAsync` never settles unless something calls `device.tick()`. Browsers do this for you.
 * Passing it in keeps that difference at the edge rather than inside the kernel, and it is
 * the difference between "a device exists" and "compute is usable".
 */
export function createGpuKernel(
  device: GPUDevice,
  shaderSource: string,
  tick?: () => void,
): GpuKernel {
  const module = device.createShaderModule({ code: shaderSource });
  const pipeline = device.createComputePipeline({
    layout: 'auto',
    compute: { module, entryPoint: 'main' },
  });

  async function computeDamageBatch(cases: Float32Array<ArrayBuffer>): Promise<Float32Array> {
    if (cases.length % CASE_STRIDE !== 0) {
      throw new Error(
        `case buffer is ${cases.length} floats, not a multiple of ${CASE_STRIDE}. A partial ` +
          `case would be read as a whole one with zeros in the missing fields, and zeros are ` +
          `legal values here — so it would score rather than fail.`,
      );
    }
    const count = cases.length / CASE_STRIDE;
    if (count === 0) return new Float32Array(0);

    const input = device.createBuffer({
      size: cases.byteLength,
      usage: USAGE_STORAGE | USAGE_COPY_DST,
    });
    device.queue.writeBuffer(input, 0, cases);

    const outputBytes = count * 4;
    const output = device.createBuffer({
      size: outputBytes,
      usage: USAGE_STORAGE | USAGE_COPY_SRC,
    });
    const staging = device.createBuffer({
      size: outputBytes,
      usage: USAGE_COPY_DST | USAGE_MAP_READ,
    });

    const bindGroup = device.createBindGroup({
      layout: pipeline.getBindGroupLayout(0),
      entries: [
        { binding: 0, resource: { buffer: input } },
        { binding: 1, resource: { buffer: output } },
      ],
    });

    const encoder = device.createCommandEncoder();
    const pass = encoder.beginComputePass();
    pass.setPipeline(pipeline);
    pass.setBindGroup(0, bindGroup);
    pass.dispatchWorkgroups(Math.ceil(count / WORKGROUP_SIZE));
    pass.end();
    encoder.copyBufferToBuffer(output, 0, staging, 0, outputBytes);
    device.queue.submit([encoder.finish()]);

    const mapped = staging.mapAsync(MAP_READ);
    const pump = tick ? setInterval(tick, 5) : undefined;
    try {
      await mapped;
    } finally {
      if (pump !== undefined) clearInterval(pump);
    }

    // Copied out before unmapping: the mapped range is a view into memory the driver
    // reclaims, and returning it would hand back a buffer that is valid until it is not.
    const result = new Float32Array(staging.getMappedRange().slice(0));
    staging.unmap();
    input.destroy();
    output.destroy();
    staging.destroy();
    return result;
  }

  return { computeDamageBatch, destroy: () => module };
}
