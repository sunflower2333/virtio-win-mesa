/*
 * Copyright 2026 DroidVM contributors
 * SPDX-License-Identifier: MIT
 */

#include <d3d11.h>
#include <windows.h>
#include <wrl/client.h>

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

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

   LoadedModule software_module = {
      LoadLibraryExW(L"viogpud3d-zink.dll", nullptr,
                     LOAD_LIBRARY_SEARCH_APPLICATION_DIR |
                        LOAD_LIBRARY_SEARCH_SYSTEM32),
   };
   if (!software_module.handle)
      return fail("LoadLibraryExW(viogpud3d-zink.dll)",
                  HRESULT_FROM_WIN32(GetLastError()));

   const D3D_FEATURE_LEVEL requested_levels[] = {
      D3D_FEATURE_LEVEL_11_0,
      D3D_FEATURE_LEVEL_10_1,
      D3D_FEATURE_LEVEL_10_0,
   };
   D3D_FEATURE_LEVEL feature_level = D3D_FEATURE_LEVEL_10_0;
   ComPtr<ID3D11Device> device;
   ComPtr<ID3D11DeviceContext> context;
   HRESULT result = D3D11CreateDevice(
      nullptr, D3D_DRIVER_TYPE_SOFTWARE, software_module.handle, 0,
      requested_levels, ARRAYSIZE(requested_levels), D3D11_SDK_VERSION,
      &device, &feature_level, &context);
   if (FAILED(result))
      return fail("D3D11CreateDevice", result);

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

   context->CopyResource(staging.Get(), render_target.Get());

   D3D11_MAPPED_SUBRESOURCE mapped = {};
   result = context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped);
   if (FAILED(result))
      return fail("Map(staging)", result);
   if (mapped.RowPitch < kWidth * 4) {
      context->Unmap(staging.Get(), 0);
      fprintf(stderr, "invalid staging row pitch: %u\n", mapped.RowPitch);
      return EXIT_FAILURE;
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
   context->Unmap(staging.Get(), 0);

   if (invalid_x != kWidth) {
      fprintf(stderr, "unexpected pixel at (%u, %u)\n", invalid_x, invalid_y);
      return EXIT_FAILURE;
   }
   if (checksum != kExpectedChecksum) {
      fprintf(stderr, "checksum mismatch: expected %llu, got %llu\n",
              static_cast<unsigned long long>(kExpectedChecksum),
              static_cast<unsigned long long>(checksum));
      return EXIT_FAILURE;
   }

   printf("Zink D3D11 offscreen draw probe: PASS feature_level=0x%x checksum=%llu\n",
          static_cast<unsigned>(feature_level),
          static_cast<unsigned long long>(checksum));
   return EXIT_SUCCESS;
}
