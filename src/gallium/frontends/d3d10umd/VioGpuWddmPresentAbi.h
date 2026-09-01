/*
 * Copyright 2026 DroidVM contributors
 * SPDX-License-Identifier: MIT
 *
 * Minimal exact-revision allocation ABI used by the Zink D3D Present bridge.
 * Keep this layout identical to viogpu/shared/viogpu_wddm_abi.h.
 */

#ifndef VIOGPU_WDDM_PRESENT_ABI_H
#define VIOGPU_WDDM_PRESENT_ABI_H

#include <stddef.h>
#include <stdint.h>

#define VIOGPU_WDDM_ABI_MAGIC 0x504D5644U
#define VIOGPU_WDDM_ABI_VERSION 0U

#define VIOGPU_WDDM_ALLOCATION_PRIMARY 0x00000001U
#define VIOGPU_WDDM_ALLOCATION_CPU_VISIBLE 0x00000002U

#define VIOGPU_WDDM_FORMAT_B8G8R8A8_UNORM 1U
#define VIOGPU_WDDM_FORMAT_B8G8R8X8_UNORM 2U

#pragma pack(push, 4)

struct VioGpuWddmAbiHeader {
   uint32_t Magic;
   uint32_t Version;
   uint32_t Size;
   uint32_t Reserved;
};

struct VioGpuWddmAllocationInfo {
   VioGpuWddmAbiHeader Header;
   uint64_t Size;
   uint64_t Alignment;
   uint64_t RequestedIova;
   uint64_t ExpectedResetGeneration;
   uint32_t Flags;
   uint32_t Format;
   uint32_t Width;
   uint32_t Height;
   uint32_t Pitch;
   uint32_t RefreshRateNumerator;
   uint32_t RefreshRateDenominator;
   uint32_t ContextId;
};

#pragma pack(pop)

static_assert(sizeof(VioGpuWddmAbiHeader) == 16,
              "VioGPU WDDM ABI header layout changed");
static_assert(sizeof(VioGpuWddmAllocationInfo) == 80,
              "VioGPU WDDM allocation ABI layout changed");
static_assert(offsetof(VioGpuWddmAllocationInfo, Flags) == 48,
              "VioGPU WDDM allocation flags offset changed");
static_assert(offsetof(VioGpuWddmAllocationInfo, ContextId) == 76,
              "VioGPU WDDM allocation context offset changed");

#endif
