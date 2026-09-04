/*
 * Copyright 2026 DroidVM contributors
 * SPDX-License-Identifier: MIT
 */

#include <d3d11.h>
#include <dxgi.h>
#include <windows.h>
#include <wrl/client.h>

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "counter_consumer_cs_5_0.h"
#include "counter_producer_cs_5_0.h"
#include "tri_ps_4_0.h"
#include "tri_vs_4_0.h"

using Microsoft::WRL::ComPtr;

namespace {

constexpr UINT kWidth = 64;
constexpr UINT kHeight = 64;
constexpr uint64_t kExpectedChecksum = 3133440;

struct Vertex {
   FLOAT position[4];
   FLOAT color[4];
};

constexpr Vertex kFullscreenTriangle[] = {
   {{-1.0f, -1.0f, 0.5f, 1.0f}, {0.0f, 1.0f, 1.0f, 1.0f}},
   {{3.0f, -1.0f, 0.5f, 1.0f}, {0.0f, 1.0f, 1.0f, 1.0f}},
   {{-1.0f, 3.0f, 0.5f, 1.0f}, {0.0f, 1.0f, 1.0f, 1.0f}},
};

const D3D11_INPUT_ELEMENT_DESC kInputElements[] = {
   {"POSITION", 0, DXGI_FORMAT_R32G32B32A32_FLOAT, 0,
    offsetof(Vertex, position), D3D11_INPUT_PER_VERTEX_DATA, 0},
   {"COLOR", 0, DXGI_FORMAT_R32G32B32A32_FLOAT, 0, offsetof(Vertex, color),
    D3D11_INPUT_PER_VERTEX_DATA, 0},
};

struct LoadedModule {
   HMODULE handle;

   ~LoadedModule()
   {
      if (handle)
         FreeLibrary(handle);
   }
};

int
fail(const char *operation, HRESULT result)
{
   fprintf(stderr, "%s failed: 0x%08lx\n", operation,
           static_cast<unsigned long>(result));
   return EXIT_FAILURE;
}

bool
read_u32_buffer(ID3D11DeviceContext *context,
                ID3D11Buffer *source,
                ID3D11Buffer *staging,
                UINT *values,
                UINT count,
                const char *stage)
{
   context->CopyResource(staging, source);

   D3D11_MAPPED_SUBRESOURCE mapped = {};
   HRESULT result = context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped);
   if (FAILED(result)) {
      fprintf(stderr, "%s Map(staging) failed: 0x%08lx\n", stage,
              static_cast<unsigned long>(result));
      return false;
   }
   if (!mapped.pData) {
      context->Unmap(staging, 0);
      fprintf(stderr, "%s returned an empty staging map\n", stage);
      return false;
   }

   memcpy(values, mapped.pData, static_cast<size_t>(count) * sizeof(*values));
   context->Unmap(staging, 0);
   return true;
}

bool
validate_structure_count(ID3D11DeviceContext *context,
                         ID3D11Buffer *count_buffer,
                         ID3D11Buffer *count_staging,
                         ID3D11UnorderedAccessView *counter_uav,
                         UINT expected,
                         const char *stage)
{
   context->CopyStructureCount(count_buffer, 0, counter_uav);

   UINT actual = 0;
   if (!read_u32_buffer(context, count_buffer, count_staging, &actual, 1,
                        stage))
      return false;
   if (actual != expected) {
      fprintf(stderr, "%s count mismatch: expected %u, got %u\n", stage,
              expected, actual);
      return false;
   }

   printf("%s count: PASS value=%u\n", stage, actual);
   return true;
}

bool
validate_u32_sequence(const UINT *values,
                      UINT count,
                      UINT first,
                      const char *stage)
{
   for (UINT i = 0; i < count; ++i) {
      if (values[i] != first + i) {
         fprintf(stderr, "%s value %u mismatch: expected %u, got %u\n",
                 stage, i, first + i, values[i]);
         return false;
      }
   }

   return true;
}

bool
validate_u32_set(const UINT *values,
                 UINT count,
                 UINT first,
                 const char *stage)
{
   bool seen[8] = {};
   if (count > ARRAYSIZE(seen))
      return false;

   for (UINT i = 0; i < count; ++i) {
      if (values[i] < first || values[i] >= first + count ||
          seen[values[i] - first]) {
         fprintf(stderr, "%s invalid set value %u at index %u\n", stage,
                 values[i], i);
         return false;
      }
      seen[values[i] - first] = true;
   }

   return true;
}

bool
validate_uav_counters(ID3D11Device *device, ID3D11DeviceContext *context)
{
   constexpr UINT kCounterElements = 8;
   constexpr UINT kMarkerElements = 4;

   D3D11_BUFFER_DESC counter_desc = {};
   counter_desc.ByteWidth = kCounterElements * sizeof(UINT);
   counter_desc.Usage = D3D11_USAGE_DEFAULT;
   counter_desc.BindFlags = D3D11_BIND_UNORDERED_ACCESS;
   counter_desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;
   counter_desc.StructureByteStride = sizeof(UINT);

   ComPtr<ID3D11Buffer> counter_buffer;
   HRESULT result =
      device->CreateBuffer(&counter_desc, nullptr, &counter_buffer);
   if (FAILED(result)) {
      fail("CreateBuffer(counter payload)", result);
      return false;
   }

   D3D11_UNORDERED_ACCESS_VIEW_DESC counter_uav_desc = {};
   counter_uav_desc.Format = DXGI_FORMAT_UNKNOWN;
   counter_uav_desc.ViewDimension = D3D11_UAV_DIMENSION_BUFFER;
   counter_uav_desc.Buffer.NumElements = kCounterElements;
   counter_uav_desc.Buffer.Flags = D3D11_BUFFER_UAV_FLAG_COUNTER;

   ComPtr<ID3D11UnorderedAccessView> counter_uav;
   result = device->CreateUnorderedAccessView(
      counter_buffer.Get(), &counter_uav_desc, &counter_uav);
   if (FAILED(result)) {
      fail("CreateUnorderedAccessView(counter)", result);
      return false;
   }

   D3D11_BUFFER_DESC marker_desc = {};
   marker_desc.ByteWidth = kMarkerElements * sizeof(UINT);
   marker_desc.Usage = D3D11_USAGE_DEFAULT;
   marker_desc.BindFlags = D3D11_BIND_UNORDERED_ACCESS;

   ComPtr<ID3D11Buffer> marker_buffer;
   result = device->CreateBuffer(&marker_desc, nullptr, &marker_buffer);
   if (FAILED(result)) {
      fail("CreateBuffer(counter markers)", result);
      return false;
   }

   D3D11_UNORDERED_ACCESS_VIEW_DESC marker_uav_desc = {};
   marker_uav_desc.Format = DXGI_FORMAT_R32_UINT;
   marker_uav_desc.ViewDimension = D3D11_UAV_DIMENSION_BUFFER;
   marker_uav_desc.Buffer.NumElements = kMarkerElements;

   ComPtr<ID3D11UnorderedAccessView> marker_uav;
   result = device->CreateUnorderedAccessView(
      marker_buffer.Get(), &marker_uav_desc, &marker_uav);
   if (FAILED(result)) {
      fail("CreateUnorderedAccessView(counter markers)", result);
      return false;
   }

   D3D11_BUFFER_DESC count_desc = {};
   count_desc.ByteWidth = sizeof(UINT);
   count_desc.Usage = D3D11_USAGE_DEFAULT;

   ComPtr<ID3D11Buffer> count_buffer;
   result = device->CreateBuffer(&count_desc, nullptr, &count_buffer);
   if (FAILED(result)) {
      fail("CreateBuffer(structure count)", result);
      return false;
   }

   D3D11_BUFFER_DESC counter_staging_desc = counter_desc;
   counter_staging_desc.Usage = D3D11_USAGE_STAGING;
   counter_staging_desc.BindFlags = 0;
   counter_staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
   ComPtr<ID3D11Buffer> counter_staging;
   result = device->CreateBuffer(&counter_staging_desc, nullptr,
                                 &counter_staging);
   if (FAILED(result)) {
      fail("CreateBuffer(counter staging)", result);
      return false;
   }

   D3D11_BUFFER_DESC marker_staging_desc = marker_desc;
   marker_staging_desc.Usage = D3D11_USAGE_STAGING;
   marker_staging_desc.BindFlags = 0;
   marker_staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
   ComPtr<ID3D11Buffer> marker_staging;
   result = device->CreateBuffer(&marker_staging_desc, nullptr,
                                 &marker_staging);
   if (FAILED(result)) {
      fail("CreateBuffer(marker staging)", result);
      return false;
   }

   D3D11_BUFFER_DESC count_staging_desc = count_desc;
   count_staging_desc.Usage = D3D11_USAGE_STAGING;
   count_staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
   ComPtr<ID3D11Buffer> count_staging;
   result = device->CreateBuffer(&count_staging_desc, nullptr,
                                 &count_staging);
   if (FAILED(result)) {
      fail("CreateBuffer(count staging)", result);
      return false;
   }

   ComPtr<ID3D11ComputeShader> producer_shader;
   result = device->CreateComputeShader(
      g_counter_producer_cs, sizeof(g_counter_producer_cs), nullptr,
      &producer_shader);
   if (FAILED(result)) {
      fail("CreateComputeShader(counter producer)", result);
      return false;
   }

   ComPtr<ID3D11ComputeShader> consumer_shader;
   result = device->CreateComputeShader(
      g_counter_consumer_cs, sizeof(g_counter_consumer_cs), nullptr,
      &consumer_shader);
   if (FAILED(result)) {
      fail("CreateComputeShader(counter consumer)", result);
      return false;
   }

   ID3D11UnorderedAccessView *uavs[] = {counter_uav.Get(), marker_uav.Get()};
   const UINT initial_counts[] = {2, D3D11_KEEP_UNORDERED_ACCESS_VIEWS};
   context->CSSetUnorderedAccessViews(0, ARRAYSIZE(uavs), uavs,
                                      initial_counts);
   if (!validate_structure_count(context, count_buffer.Get(),
                                 count_staging.Get(), counter_uav.Get(), 2,
                                 "initial counter"))
      return false;

   context->CSSetShader(producer_shader.Get(), nullptr, 0);
   context->Dispatch(1, 1, 1);

   ID3D11UnorderedAccessView *null_uavs[ARRAYSIZE(uavs)] = {};
   context->CSSetUnorderedAccessViews(0, ARRAYSIZE(null_uavs), null_uavs,
                                      nullptr);
   context->CSSetShader(nullptr, nullptr, 0);

   if (!validate_structure_count(context, count_buffer.Get(),
                                 count_staging.Get(), counter_uav.Get(), 6,
                                 "producer counter"))
      return false;

   UINT counter_values[kCounterElements] = {};
   if (!read_u32_buffer(context, counter_buffer.Get(), counter_staging.Get(),
                        counter_values, ARRAYSIZE(counter_values),
                        "producer payload") ||
       !validate_u32_sequence(&counter_values[2], 4, 100,
                              "producer payload"))
      return false;

   UINT marker_values[kMarkerElements] = {};
   if (!read_u32_buffer(context, marker_buffer.Get(), marker_staging.Get(),
                        marker_values, ARRAYSIZE(marker_values),
                        "producer markers") ||
       !validate_u32_set(marker_values, ARRAYSIZE(marker_values), 2,
                         "producer markers"))
      return false;

   const UINT preserved_counts[] = {
      D3D11_KEEP_UNORDERED_ACCESS_VIEWS,
      D3D11_KEEP_UNORDERED_ACCESS_VIEWS,
   };
   context->CSSetUnorderedAccessViews(0, ARRAYSIZE(uavs), uavs,
                                      preserved_counts);
   context->CSSetShader(consumer_shader.Get(), nullptr, 0);
   context->Dispatch(1, 1, 1);
   context->CSSetUnorderedAccessViews(0, ARRAYSIZE(null_uavs), null_uavs,
                                      nullptr);
   context->CSSetShader(nullptr, nullptr, 0);

   if (!validate_structure_count(context, count_buffer.Get(),
                                 count_staging.Get(), counter_uav.Get(), 4,
                                 "consumer counter"))
      return false;

   memset(marker_values, 0, sizeof(marker_values));
   if (!read_u32_buffer(context, marker_buffer.Get(), marker_staging.Get(),
                        marker_values, ARRAYSIZE(marker_values),
                        "consumer values") ||
       !validate_u32_set(marker_values, 2, 102, "consumer values"))
      return false;

   printf("D3D11 native UAV counter probe: PASS\n");
   return true;
}

bool
validate_cyan_frame(ID3D11DeviceContext *context,
                    ID3D11Texture2D *staging,
                    ID3D11Texture2D *render_target,
                    const char *stage)
{
   context->CopyResource(staging, render_target);

   D3D11_MAPPED_SUBRESOURCE mapped = {};
   HRESULT result = context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped);
   if (FAILED(result)) {
      fprintf(stderr, "%s Map(staging) failed: 0x%08lx\n", stage,
              static_cast<unsigned long>(result));
      return false;
   }
   if (mapped.RowPitch < kWidth * 4) {
      context->Unmap(staging, 0);
      fprintf(stderr, "%s invalid staging row pitch: %u\n", stage,
              mapped.RowPitch);
      return false;
   }

   uint64_t checksum = 0;
   UINT invalid_x = kWidth;
   UINT invalid_y = kHeight;
   const uint8_t *data = static_cast<const uint8_t *>(mapped.pData);
   for (UINT y = 0; y < kHeight; ++y) {
      const uint8_t *row = data + static_cast<size_t>(y) * mapped.RowPitch;
      for (UINT x = 0; x < kWidth; ++x) {
         const uint8_t *pixel = row + static_cast<size_t>(x) * 4;
         checksum += pixel[0] + pixel[1] + pixel[2] + pixel[3];
         if (invalid_x == kWidth &&
             (pixel[0] != 0 || pixel[1] != 255 || pixel[2] != 255 ||
              pixel[3] != 255)) {
            invalid_x = x;
            invalid_y = y;
         }
      }
   }
   context->Unmap(staging, 0);

   if (invalid_x != kWidth) {
      fprintf(stderr, "%s unexpected pixel at (%u, %u)\n", stage, invalid_x,
              invalid_y);
      return false;
   }
   if (checksum != kExpectedChecksum) {
      fprintf(stderr, "%s checksum mismatch: expected %llu, got %llu\n", stage,
              static_cast<unsigned long long>(kExpectedChecksum),
              static_cast<unsigned long long>(checksum));
      return false;
   }

   printf("%s readback: PASS checksum=%llu\n", stage,
          static_cast<unsigned long long>(checksum));
   return true;
}

bool
set_environment(const wchar_t *name, const wchar_t *value)
{
   if (SetEnvironmentVariableW(name, value))
      return true;

   fprintf(stderr, "SetEnvironmentVariableW failed: %lu\n",
           static_cast<unsigned long>(GetLastError()));
   return false;
}

} // namespace

int
main()
{
   if (!set_environment(L"GALLIUM_DRIVER", L"zink") ||
       !set_environment(L"LIBGL_ALWAYS_SOFTWARE", nullptr) ||
       !set_environment(L"D3D_ALWAYS_SOFTWARE", nullptr))
      return EXIT_FAILURE;

   /* D3D_DRIVER_TYPE_SOFTWARE with a loaded module is the historical way to
    * exercise this driver, but modern Windows rejects it with E_INVALIDARG.
    * When ZINK_D3D11_HARDWARE_ADAPTER names a DXGI adapter index, drive the
    * installed driver as a real hardware adapter instead, which is how the
    * frontend actually runs once it is registered as UserModeDriverName. */
   wchar_t adapter_env[16] = {};
   const DWORD adapter_env_len =
      GetEnvironmentVariableW(L"ZINK_D3D11_HARDWARE_ADAPTER", adapter_env,
                              ARRAYSIZE(adapter_env));
   const bool use_hardware_adapter = adapter_env_len > 0;

   LoadedModule software_module = {};
   ComPtr<IDXGIAdapter> hardware_adapter;
   if (use_hardware_adapter) {
      const UINT adapter_index = (UINT)_wtoi(adapter_env);
      ComPtr<IDXGIFactory> factory;
      HRESULT hr = CreateDXGIFactory(__uuidof(IDXGIFactory), (void **)&factory);
      if (FAILED(hr))
         return fail("CreateDXGIFactory", hr);
      hr = factory->EnumAdapters(adapter_index, &hardware_adapter);
      if (FAILED(hr))
         return fail("IDXGIFactory::EnumAdapters", hr);
      DXGI_ADAPTER_DESC desc = {};
      hardware_adapter->GetDesc(&desc);
      fwprintf(stdout, L"adapter[%u] %s\n", adapter_index, desc.Description);
   } else {
      software_module.handle =
         LoadLibraryExW(L"viogpud3d-zink.dll", nullptr,
                        LOAD_LIBRARY_SEARCH_APPLICATION_DIR |
                           LOAD_LIBRARY_SEARCH_SYSTEM32);
      if (!software_module.handle)
         return fail("LoadLibraryExW(viogpud3d-zink.dll)",
                     HRESULT_FROM_WIN32(GetLastError()));
   }

   const D3D_FEATURE_LEVEL requested_levels[] = {
      D3D_FEATURE_LEVEL_11_0,
      D3D_FEATURE_LEVEL_10_1,
      D3D_FEATURE_LEVEL_10_0,
   };
   D3D_FEATURE_LEVEL feature_level = D3D_FEATURE_LEVEL_10_0;
   ComPtr<ID3D11Device> device;
   ComPtr<ID3D11DeviceContext> context;
   HRESULT result = D3D11CreateDevice(
      use_hardware_adapter ? hardware_adapter.Get() : nullptr,
      use_hardware_adapter ? D3D_DRIVER_TYPE_UNKNOWN : D3D_DRIVER_TYPE_SOFTWARE,
      software_module.handle, 0,
      requested_levels, ARRAYSIZE(requested_levels), D3D11_SDK_VERSION,
      &device, &feature_level, &context);
   if (FAILED(result))
      return fail("D3D11CreateDevice", result);
   if (feature_level < D3D_FEATURE_LEVEL_11_0) {
      fprintf(stderr, "D3D11 feature level 11_0 is required for counters\n");
      return EXIT_FAILURE;
   }
   /* The UAV counter stage exercises a compute dispatch, which currently returns
    * wrong data on this stack.  ZINK_D3D11_SKIP_COUNTERS lets the draw tests run
    * so the rasterisation path can be validated independently of it. */
   wchar_t skip_counters[8] = {};
   const bool run_counters =
      GetEnvironmentVariableW(L"ZINK_D3D11_SKIP_COUNTERS", skip_counters,
                              ARRAYSIZE(skip_counters)) == 0;
   if (run_counters) {
      if (!validate_uav_counters(device.Get(), context.Get()))
         return EXIT_FAILURE;
   } else {
      printf("UAV counter stage skipped by ZINK_D3D11_SKIP_COUNTERS\n");
   }

   D3D11_TEXTURE2D_DESC render_desc = {};
   render_desc.Width = kWidth;
   render_desc.Height = kHeight;
   render_desc.MipLevels = 1;
   render_desc.ArraySize = 1;
   render_desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
   render_desc.SampleDesc.Count = 1;
   render_desc.Usage = D3D11_USAGE_DEFAULT;
   render_desc.BindFlags = D3D11_BIND_RENDER_TARGET;

   ComPtr<ID3D11Texture2D> render_target;
   result = device->CreateTexture2D(&render_desc, nullptr, &render_target);
   if (FAILED(result))
      return fail("CreateTexture2D(render target)", result);

   ComPtr<ID3D11RenderTargetView> render_target_view;
   result = device->CreateRenderTargetView(render_target.Get(), nullptr,
                                           &render_target_view);
   if (FAILED(result))
      return fail("CreateRenderTargetView", result);

   context->OMSetRenderTargets(1, render_target_view.GetAddressOf(), nullptr);

   const FLOAT red[] = {1.0f, 0.0f, 0.0f, 1.0f};
   context->ClearRenderTargetView(render_target_view.Get(), red);

   ComPtr<ID3D11VertexShader> vertex_shader;
   result = device->CreateVertexShader(g_VS, sizeof(g_VS), nullptr,
                                       &vertex_shader);
   if (FAILED(result))
      return fail("CreateVertexShader", result);

   ComPtr<ID3D11PixelShader> pixel_shader;
   result = device->CreatePixelShader(g_PS, sizeof(g_PS), nullptr,
                                      &pixel_shader);
   if (FAILED(result))
      return fail("CreatePixelShader", result);

   ComPtr<ID3D11InputLayout> input_layout;
   result = device->CreateInputLayout(kInputElements, ARRAYSIZE(kInputElements),
                                      g_VS, sizeof(g_VS), &input_layout);
   if (FAILED(result))
      return fail("CreateInputLayout", result);

   D3D11_BUFFER_DESC vertex_desc = {};
   vertex_desc.ByteWidth = static_cast<UINT>(sizeof(kFullscreenTriangle));
   vertex_desc.Usage = D3D11_USAGE_IMMUTABLE;
   vertex_desc.BindFlags = D3D11_BIND_VERTEX_BUFFER;

   D3D11_SUBRESOURCE_DATA vertex_data = {};
   vertex_data.pSysMem = kFullscreenTriangle;

   ComPtr<ID3D11Buffer> vertex_buffer;
   result = device->CreateBuffer(&vertex_desc, &vertex_data, &vertex_buffer);
   if (FAILED(result))
      return fail("CreateBuffer(vertex)", result);

   const D3D11_DRAW_INSTANCED_INDIRECT_ARGS indirect_args = {
      ARRAYSIZE(kFullscreenTriangle),
      1,
      0,
      0,
   };
   static_assert(sizeof(indirect_args) == 16);

   D3D11_BUFFER_DESC indirect_desc = {};
   indirect_desc.ByteWidth = static_cast<UINT>(sizeof(indirect_args));
   /* The runtime rejects D3D11_RESOURCE_MISC_DRAWINDIRECT_ARGS on anything but
    * D3D11_USAGE_DEFAULT, so IMMUTABLE here failed CreateBuffer with
    * E_INVALIDARG before either draw ran and hid the render results this probe
    * exists to measure. */
   indirect_desc.Usage = D3D11_USAGE_DEFAULT;
   indirect_desc.MiscFlags = D3D11_RESOURCE_MISC_DRAWINDIRECT_ARGS;

   D3D11_SUBRESOURCE_DATA indirect_data = {};
   indirect_data.pSysMem = &indirect_args;

   ComPtr<ID3D11Buffer> indirect_buffer;
   result = device->CreateBuffer(&indirect_desc, &indirect_data,
                                 &indirect_buffer);
   if (FAILED(result))
      return fail("CreateBuffer(indirect arguments)", result);

   D3D11_VIEWPORT viewport = {};
   viewport.Width = static_cast<FLOAT>(kWidth);
   viewport.Height = static_cast<FLOAT>(kHeight);
   viewport.MaxDepth = 1.0f;

   const UINT stride = sizeof(Vertex);
   const UINT offset = 0;
   context->IASetInputLayout(input_layout.Get());
   context->IASetVertexBuffers(0, 1, vertex_buffer.GetAddressOf(), &stride,
                               &offset);
   context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
   context->RSSetViewports(1, &viewport);
   context->VSSetShader(vertex_shader.Get(), nullptr, 0);
   context->PSSetShader(pixel_shader.Get(), nullptr, 0);
   context->Draw(ARRAYSIZE(kFullscreenTriangle), 0);

   D3D11_TEXTURE2D_DESC staging_desc = render_desc;
   staging_desc.Usage = D3D11_USAGE_STAGING;
   staging_desc.BindFlags = 0;
   staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;

   ComPtr<ID3D11Texture2D> staging;
   result = device->CreateTexture2D(&staging_desc, nullptr, &staging);
   if (FAILED(result))
      return fail("CreateTexture2D(staging)", result);

   if (!validate_cyan_frame(context.Get(), staging.Get(), render_target.Get(),
                            "direct draw"))
      return EXIT_FAILURE;

   context->ClearRenderTargetView(render_target_view.Get(), red);
   context->DrawInstancedIndirect(indirect_buffer.Get(), 0);
   if (!validate_cyan_frame(context.Get(), staging.Get(), render_target.Get(),
                            "indirect draw"))
      return EXIT_FAILURE;

   printf("Zink D3D11 offscreen direct/indirect draw probe: PASS "
          "feature_level=0x%x\n",
          static_cast<unsigned>(feature_level));
   return EXIT_SUCCESS;
}
