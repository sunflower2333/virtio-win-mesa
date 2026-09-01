/**************************************************************************
 *
 * Copyright 2012-2021 VMware, Inc.
 * All Rights Reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the
 * "Software"), to deal in the Software without restriction, including
 * without limitation the rights to use, copy, modify, merge, publish,
 * distribute, sub license, and/or sell copies of the Software, and to
 * permit persons to whom the Software is furnished to do so, subject to
 * the following conditions:
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NON-INFRINGEMENT. IN NO EVENT SHALL
 * THE COPYRIGHT HOLDERS, AUTHORS AND/OR ITS SUPPLIERS BE LIABLE FOR ANY CLAIM,
 * DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
 * OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
 * USE OR OTHER DEALINGS IN THE SOFTWARE.
 *
 * The above copyright notice and this permission notice (including the
 * next paragraph) shall be included in all copies or substantial portions
 * of the Software.
 *
 **************************************************************************/

/*
 * DxgiFns.cpp --
 *    DXGI related functions.
 */

#include <stdint.h>
#include <stdarg.h>
#include <stdlib.h>
#include <windows.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <winerror.h>
#include <winnt.h>

#include "DxgiFns.h"
#include "Resource.h"

#include <d3d9.h>
#include <d3dkmthk.h>

#include "Format.h"
#include "Shader.h"
#include "State.h"

#include "Debug.h"

#include "frontend/winsys_handle.h"
#include "pipe/p_defines.h"
#include "pipe/p_state.h"
#include "util/format/u_format.h"
#include "util/u_debug.h"
#include "util/u_inlines.h"
#include "util/u_math.h"
#include "gallium/winsys/yttrium/gdi/yttrium_gdi_public.h"

static const char *
dxgi_screen_name(Device *device)
{
   if (!device || !device->screen || !device->screen->get_name) {
      return "<unknown>";
   }

   const char *name = device->screen->get_name(device->screen);
   return name ? name : "<unknown>";
}

static bool
dxgi_is_yttrium_screen(Device *device)
{
   return strcmp(dxgi_screen_name(device), "yttrium") == 0;
}

static bool
dxgi_is_zink_screen(Device *device)
{
   return device && device->device.base.d3d10_zink;
}

static void
dxgi_sync_yttrium_primary_identity(Device *device, Resource *resource)
{
   if (!dxgi_is_yttrium_screen(device) || !resource || !resource->resource) {
      return;
   }

   yttrium_gdi_resource_set_primary_target(resource->resource,
                                           resource->yttrium_primary);
}

static D3DKMT_HANDLE
dxgi_get_d3dkmt_render_allocation(Device *device, Resource *resource)
{
   struct winsys_handle whandle;

   if (!device || !resource || !device->screen ||
       !device->screen->resource_get_handle ||
       !resource->resource)
      return 0;

   memset(&whandle, 0, sizeof(whandle));
   whandle.type = WINSYS_HANDLE_TYPE_D3DKMT_ALLOC;
   if (!device->screen->resource_get_handle(device->screen, device->pipe,
                                            resource->resource, &whandle, 0))
      return 0;

   return (D3DKMT_HANDLE)(uintptr_t)whandle.handle;
}

static HRESULT
dxgi_collect_d3dkmt_render_allocations(
   Device *device,
   const DXGI_DDI_HRESOURCE *resources,
   UINT resource_count,
   D3DKMT_HANDLE **out_allocations)
{
   if (!out_allocations || !device || (resource_count && !resources))
      return E_INVALIDARG;

   *out_allocations = NULL;
   if (!resource_count)
      return S_OK;

   D3DKMT_HANDLE *allocations = (D3DKMT_HANDLE *)calloc(
      resource_count, sizeof(*allocations));
   if (!allocations)
      return E_OUTOFMEMORY;

   for (UINT i = 0; i < resource_count; ++i) {
      Resource *resource = CastResource(resources[i]);
      if (!resource || !resource->resource) {
         free(allocations);
         return E_INVALIDARG;
      }

      allocations[i] =
         dxgi_get_d3dkmt_render_allocation(device, resource);
      if (!allocations[i]) {
         free(allocations);
         return E_FAIL;
      }
   }

   *out_allocations = allocations;
   return S_OK;
}

static D3DKMT_HANDLE
dxgi_get_d3dkmt_allocation(Device *device, Resource *resource)
{
   if (!device || !resource)
      return 0;

   D3DKMT_HANDLE paired = GetZinkPresentAllocation(resource);
   if (paired)
      return paired;

   return dxgi_get_d3dkmt_render_allocation(device, resource);
}

static void
dxgi_flush_frontbuffer(Device *device,
                       struct pipe_resource *resource,
                       unsigned level,
                       unsigned layer,
                       void *context_private)
{
   if (!device || !device->pipe || !device->screen ||
       !device->screen->flush_frontbuffer || !resource) {
      return;
   }

   /* The Yttrium screen hook owns its exact asynchronous publication ticket. */
   if (!dxgi_is_yttrium_screen(device))
      yttrium_gdi_flush_labeled(device->pipe, NULL, 0,
                                "DXGI flush-frontbuffer pre-flush");
   device->screen->flush_frontbuffer(device->screen,
                                     device->pipe,
                                     resource,
                                     level,
                                     layer,
                                     context_private,
                                     0,
                                     NULL);
}

/*
 * Each of these re-reads the environment on every call, and this predicate
 * gates the present path.  The config cannot change after start-up, so answer
 * once and keep it.
 */
static bool
dxgi_yttrium_trace_option(void)
{
   static int enabled = -1;

   if (enabled < 0)
      enabled = yttrium_gdi_debug_get_bool_option(
                   "D3D10UMD_YTTRIUM_DXGI_TRACE", false) ? 1 : 0;

   return enabled != 0;
}

static bool
dxgi_yttrium_debug_trace_option(void)
{
   static int enabled = -1;

   if (enabled < 0)
      enabled = yttrium_gdi_debug_get_bool_option(
                   "D3D10UMD_DEBUG_DXGI_TRACE", false) ? 1 : 0;

   return enabled != 0;
}

DEBUG_GET_ONCE_BOOL_OPTION(dxgi_trace, "D3D10UMD_DEBUG_DXGI_TRACE", false)

static bool
dxgi_trace_enabled(Device *device)
{
   if (dxgi_is_yttrium_screen(device)) {
      static volatile LONG logged_trace_config;
      const bool yttrium_trace = dxgi_yttrium_trace_option();
      const bool yttrium_debug_trace = dxgi_yttrium_debug_trace_option();
      const bool mesa_debug_trace = debug_get_option_dxgi_trace();

      if (InterlockedCompareExchange(&logged_trace_config, 1, 0) == 0) {
         yttrium_gdi_user_logf(
            "yttrium: dxgi trace config YTTRIUM_DXGI_TRACE=%u DEBUG_DXGI_TRACE(config/env)=%u DEBUG_DXGI_TRACE(mesa-env)=%u enabled=%u\n",
            yttrium_trace, yttrium_debug_trace, mesa_debug_trace,
            yttrium_trace || yttrium_debug_trace || mesa_debug_trace);
      }

      return yttrium_trace || yttrium_debug_trace || mesa_debug_trace;
   }

   return debug_get_option_dxgi_trace();
}

static void
dxgi_trace_printf(Device *device, const char *format, ...)
{
   char message[1024];
   va_list ap;

   if (!format)
      return;

   va_start(ap, format);
   vsnprintf(message, sizeof(message), format, ap);
   va_end(ap);
   message[sizeof(message) - 1] = '\0';

   if (dxgi_is_yttrium_screen(device)) {
      yttrium_gdi_user_logf("%s", message);
      OutputDebugStringA(message);
   } else {
      DebugPrintf("%s", message);
   }
}

static void
dxgi_trace_resource(Device *device, const char *label, Resource *resource)
{
   if (!dxgi_trace_enabled(device)) {
      return;
   }

   struct pipe_resource *pipe_resource = resource ? resource->resource : NULL;
   if (!pipe_resource) {
      dxgi_trace_printf(device,
                        "d3d10umd: dxgi %s resource=%p pipe_resource=%p\n",
                        label, resource, pipe_resource);
      return;
   }

   dxgi_trace_printf(device,
                     "d3d10umd: dxgi %s resource=%p pipe_resource=%p target=%u %ux%ux%u levels=%u array=%u format=%s bind=0x%x flags=0x%x usage=%u samples=%u\n",
                     label,
                     resource,
                     pipe_resource,
                     pipe_resource->target,
                     pipe_resource->width0,
                     pipe_resource->height0,
                     pipe_resource->depth0,
                     pipe_resource->last_level + 1,
                     pipe_resource->array_size,
                     util_format_name(pipe_resource->format),
                     pipe_resource->bind,
                     pipe_resource->flags,
                     pipe_resource->usage,
                     pipe_resource->nr_samples);
   yttrium_gdi_resource_debug_log(pipe_resource, label);
}

/*
 * Present model the runtime picked for this present, from the present history
 * token.  Distinguishes the GPU-composited paths (redirected_flip,
 * redirected_composition) from the legacy GDI redirection paths that win32k
 * services in software.
 */
static const char *
dxgi_present_model_name(unsigned model)
{
   static const char *names[] = {
      "uninitialized",
      "redirected_gdi",
      "redirected_flip",
      "redirected_blt",
      "redirected_vistablt",
      "screencapturefence",
      "redirected_gdi_sysmem",
      "redirected_composition",
      "surfacecomplete",
      "flipmanager",
   };

   return model < sizeof(names) / sizeof(names[0]) ? names[model] : "unknown";
}

static void
dxgi_trace_present_context(Device *device, const char *label, void *context)
{
   if (!dxgi_trace_enabled(device)) {
      return;
   }

   if (!context) {
      dxgi_trace_printf(device, "d3d10umd: dxgi %s context=NULL\n",
                        label);
      return;
   }

   D3DKMT_PRESENT *present = (D3DKMT_PRESENT *)context;
   dxgi_trace_printf(device,
                     "d3d10umd: dxgi %s context=%p hWindow=%p hSource=0x%lx hDestination=0x%lx flags=0x%x flip=%u present_count=%u model=%u(%s) token_size=%u comp_binding=0x%llx src={%ld,%ld,%ld,%ld} dst={%ld,%ld,%ld,%ld} subrects=%u optimize=%u private_size=%u\n",
                     label,
                     context,
                     present->hWindow,
                     (unsigned long)present->hSource,
                     (unsigned long)present->hDestination,
                     present->Flags.Value,
                     present->FlipInterval,
                     present->PresentCount,
                     (unsigned)present->PresentHistoryToken.Model,
                     dxgi_present_model_name(
                        (unsigned)present->PresentHistoryToken.Model),
                     present->PresentHistoryToken.TokenSize,
                     (unsigned long long)
                        present->PresentHistoryToken.CompositionBindingId,
                     present->SrcRect.left,
                     present->SrcRect.top,
                     present->SrcRect.right,
                     present->SrcRect.bottom,
                     present->DstRect.left,
                     present->DstRect.top,
                     present->DstRect.right,
                     present->DstRect.bottom,
                     present->SubRectCnt,
                     present->bOptimizeForComposition ? 1 : 0,
                     present->PrivateDriverDataSize);
}

/*
 * ----------------------------------------------------------------------
 *
 * _Present --
 *
 *    This is turned into kernel callbacks rather than directly emitted
 *    as fifo packets.
 *
 * ----------------------------------------------------------------------
 */
HRESULT APIENTRY
_Present(DXGI_DDI_ARG_PRESENT *pPresentData)
{

   LOG_ENTRYPOINT();

   struct Device *device = CastDevice(pPresentData->hDevice);
   Resource *pSrcResource = CastResource(pPresentData->hSurfaceToPresent);
   const bool yttrium_screen = dxgi_is_yttrium_screen(device);
   const bool zink_screen = dxgi_is_zink_screen(device);
   const bool trace = dxgi_trace_enabled(device);
   Resource *pDstResource = CastResource(pPresentData->hDstResource);
   D3DKMT_HANDLE src_alloc = 0;
   D3DKMT_HANDLE dst_alloc = 0;
   HRESULT present_result = S_OK;
   const D3DKMT_PRESENT *dxgi_present_context =
      pPresentData->pDXGIContext ?
         (const D3DKMT_PRESENT *)pPresentData->pDXGIContext : NULL;

   if (trace) {
      dxgi_trace_printf(device,
                        "d3d10umd: dxgi Present src=%p dst=%p src_sub=%u dst_sub=%u dxgi_ctx=%p flags=0x%x flip_interval=%u screen=%s\n",
                        (void *)pPresentData->hSurfaceToPresent,
                        (void *)pPresentData->hDstResource,
                        pPresentData->SrcSubResourceIndex,
                        pPresentData->DstSubResourceIndex,
                        pPresentData->pDXGIContext,
                        pPresentData->Flags.Value,
                        pPresentData->FlipInterval,
                        dxgi_screen_name(device));
      dxgi_trace_resource(device, "Present src", pSrcResource);
      if (pPresentData->hDstResource) {
         dxgi_trace_resource(device, "Present dst",
                             CastResource(pPresentData->hDstResource));
      }
      dxgi_trace_present_context(device, "Present", pPresentData->pDXGIContext);
   }

   if (yttrium_screen) {
      src_alloc = dxgi_get_d3dkmt_allocation(device, pSrcResource);
      dst_alloc = dxgi_get_d3dkmt_allocation(device, pDstResource);
      yttrium_gdi_trace_dxgi_present(
         YTTRIUM_GDI_TRACE_DXGI_PRESENT_BEGIN,
         (uint64_t)(uintptr_t)pPresentData->hSurfaceToPresent,
         (uint64_t)(uintptr_t)pPresentData->hDstResource,
         src_alloc,
         dst_alloc,
         (uint64_t)(uintptr_t)pPresentData->pDXGIContext,
         dxgi_present_context ?
            (uint64_t)(uintptr_t)dxgi_present_context->hWindow : 0,
         dxgi_present_context ? (uint64_t)dxgi_present_context->hSource : 0,
         dxgi_present_context ?
            (uint64_t)dxgi_present_context->hDestination : 0,
         pPresentData->SrcSubResourceIndex,
         pPresentData->DstSubResourceIndex,
         pPresentData->Flags.Value,
         pPresentData->FlipInterval,
         dxgi_present_context ? dxgi_present_context->PresentCount : 0,
         0,
         0);
      yttrium_gdi_trace_debugf("yttrium: dxgi present src_resource=%p dst_resource=%p src_alloc=0x%lx dst_alloc=0x%lx src_sub=%u dst_sub=%u dxgi_context=%p flags=0x%x flip_interval=%u\n",
                               (void *)pPresentData->hSurfaceToPresent,
                               (void *)pPresentData->hDstResource,
                               (unsigned long)src_alloc,
                               (unsigned long)dst_alloc,
                               pPresentData->SrcSubResourceIndex,
                               pPresentData->DstSubResourceIndex,
                               pPresentData->pDXGIContext,
                               pPresentData->Flags.Value,
                               pPresentData->FlipInterval);
   }

   if (zink_screen) {
      /* The current VioGPU KMD implements Blt Present with a distinct primary
       * destination. Optional scanout resources opt out during creation, so a
       * NULL destination is an unsupported Flip path and must fail closed. */
      if (!pDstResource || !pDstResource->zink_present_primary ||
          pPresentData->DstSubResourceIndex != 0)
         return E_FAIL;

      src_alloc = dxgi_get_d3dkmt_allocation(device, pSrcResource);
      dst_alloc = dxgi_get_d3dkmt_allocation(device, pDstResource);
      if (!src_alloc || !dst_alloc || !device->zink_present_context)
         return E_FAIL;

      HRESULT publish = PublishZinkPresentResource(
         device, pSrcResource, pPresentData->SrcSubResourceIndex);
      if (FAILED(publish))
         return publish;

      gdikmt_present_info present_info = {};
      present_info.magic = GDIKMT_PRESENT_INFO_MAGIC;
      present_info.version = 4;
      present_info.dxgi_context = pPresentData->pDXGIContext;
      present_info.hDstAllocation = dst_alloc;
      present_info.status = S_OK;
      present_info.force_present_callback = true;
      NTSTATUS status = device->device.base.present(
         device->zink_present_context, src_alloc, &present_info, NULL);
      return (HRESULT)status;
   }

   /* dxgi_flush_frontbuffer publishes this Yttrium Present asynchronously. */
   if (!yttrium_screen)
      yttrium_gdi_flush_labeled(device->pipe, NULL, 0,
                                "DXGI Present pre-flush");

   {
      struct gdikmt_present_info present_info;
      void *present_context = pPresentData->pDXGIContext;

      memset(&present_info, 0, sizeof(present_info));
      if (yttrium_screen) {
         present_info.magic = GDIKMT_PRESENT_INFO_MAGIC;
         present_info.version = 3;
         present_info.dxgi_context = pPresentData->pDXGIContext;
         present_info.hDstAllocation = dst_alloc;
         present_info.status = S_OK;
         /* A runtime primary is not sufficient: DWM owns one too.  The direct
          * application scanout targets a real window, while DWM's compositor
          * scanout has no hWindow and must retain the pfnPresentCb path. */
         present_info.application_scanout =
            pSrcResource && pSrcResource->yttrium_primary &&
            dxgi_present_context && dxgi_present_context->hWindow != NULL;
         present_context = &present_info;
         yttrium_gdi_trace_dxgi_present(
            YTTRIUM_GDI_TRACE_DXGI_PRESENT_FLUSH_FRONTBUFFER,
            (uint64_t)(uintptr_t)pPresentData->hSurfaceToPresent,
            (uint64_t)(uintptr_t)pPresentData->hDstResource,
            src_alloc,
            dst_alloc,
            (uint64_t)(uintptr_t)pPresentData->pDXGIContext,
            dxgi_present_context ?
               (uint64_t)(uintptr_t)dxgi_present_context->hWindow : 0,
            dxgi_present_context ? (uint64_t)dxgi_present_context->hSource : 0,
            dxgi_present_context ?
               (uint64_t)dxgi_present_context->hDestination : 0,
            pPresentData->SrcSubResourceIndex,
            pPresentData->DstSubResourceIndex,
            pPresentData->Flags.Value,
            pPresentData->FlipInterval,
            dxgi_present_context ? dxgi_present_context->PresentCount : 0,
            0,
            0);
      }

      dxgi_flush_frontbuffer(device,
                             pSrcResource->resource,
                             0,
                             0,
                             present_context);
      if (yttrium_screen)
         present_result = present_info.status;
   }

   if (trace) {
      dxgi_trace_printf(device, "d3d10umd: dxgi Present complete src=%p\n",
                        (void *)pPresentData->hSurfaceToPresent);
   }
   if (yttrium_screen) {
      yttrium_gdi_trace_dxgi_present(
         YTTRIUM_GDI_TRACE_DXGI_PRESENT_END,
         (uint64_t)(uintptr_t)pPresentData->hSurfaceToPresent,
         (uint64_t)(uintptr_t)pPresentData->hDstResource,
         src_alloc,
         dst_alloc,
         (uint64_t)(uintptr_t)pPresentData->pDXGIContext,
         dxgi_present_context ?
            (uint64_t)(uintptr_t)dxgi_present_context->hWindow : 0,
         dxgi_present_context ? (uint64_t)dxgi_present_context->hSource : 0,
         dxgi_present_context ?
            (uint64_t)dxgi_present_context->hDestination : 0,
         pPresentData->SrcSubResourceIndex,
         pPresentData->DstSubResourceIndex,
         pPresentData->Flags.Value,
         pPresentData->FlipInterval,
         dxgi_present_context ? dxgi_present_context->PresentCount : 0,
         0,
         0);
   }

   return present_result;
}


/*
 * ----------------------------------------------------------------------
 *
 * _GetGammaCaps --
 *
 *    Return gamma capabilities.
 *
 * ----------------------------------------------------------------------
 */

HRESULT APIENTRY
_GetGammaCaps( DXGI_DDI_ARG_GET_GAMMA_CONTROL_CAPS *GetCaps )
{
   LOG_ENTRYPOINT();

   DXGI_GAMMA_CONTROL_CAPABILITIES *pCaps;

   pCaps = GetCaps->pGammaCapabilities;

   pCaps->ScaleAndOffsetSupported = false;
   pCaps->MinConvertedValue = 0.0;
   pCaps->MaxConvertedValue = 1.0;
   pCaps->NumGammaControlPoints = 17;

   for (UINT i = 0; i < pCaps->NumGammaControlPoints; i++) {
      pCaps->ControlPointPositions[i] = (float)i / (float)(pCaps->NumGammaControlPoints - 1);
   }

   return S_OK;
}


/*
 * ----------------------------------------------------------------------
 *
 * _SetDisplayMode --
 *
 *    Set the resource that is used to scan out to the display.
 *
 * ----------------------------------------------------------------------
 */

HRESULT APIENTRY
_SetDisplayMode( DXGI_DDI_ARG_SETDISPLAYMODE *SetDisplayMode )
{
   LOG_ENTRYPOINT();
   
   Device* device = CastDevice(SetDisplayMode->hDevice);
   Resource *res = CastResource(SetDisplayMode->hResource);
   const bool trace = dxgi_trace_enabled(device);

   if (trace) {
      dxgi_trace_printf(device,
                        "d3d10umd: dxgi SetDisplayMode resource=%p sub=%u screen=%s\n",
                        (void *)SetDisplayMode->hResource,
                        SetDisplayMode->SubResourceIndex,
                        dxgi_screen_name(device));
      dxgi_trace_resource(device, "SetDisplayMode", res);
   }

   D3DKMT_HANDLE kmt_handle = GetZinkPresentAllocation(res);
   unsigned stride = res ? res->zink_present_pitch : 0;
   uint64_t size = res ? (uint64_t)res->zink_present_pitch *
                           res->zink_present_height : 0;
   if (!kmt_handle) {
      struct winsys_handle handle;
      memset(&handle, 0, sizeof(handle));
      handle.type = WINSYS_HANDLE_TYPE_D3DKMT_ALLOC;
      if (!device->screen->resource_get_handle ||
          !device->screen->resource_get_handle(device->screen, NULL,
                                               res->resource, &handle, 0)) {
         LOG_UNSUPPORTED_ENTRYPOINT();
         if (trace) {
            dxgi_trace_printf(device,
                              "d3d10umd: dxgi SetDisplayMode skipped: allocation handle missing\n");
         }
         return S_OK;
      }
      kmt_handle = (D3DKMT_HANDLE)(uintptr_t)handle.handle;
      stride = handle.stride;
      size = handle.size;
   }
   NTSTATUS status =
      device->device.base.setDisplayMode(&device->device.base, kmt_handle);
   if (trace) {
      dxgi_trace_printf(device,
                        "d3d10umd: dxgi SetDisplayMode hAllocation=0x%lx status=0x%lx stride=%u size=0x%llx\n",
                        (unsigned long)kmt_handle,
                        status,
                        stride,
                        (unsigned long long)size);
   }

   return S_OK;
}


/*
 * ----------------------------------------------------------------------
 *
 * _SetResourcePriority --
 *
 * ----------------------------------------------------------------------
 */

HRESULT APIENTRY
_SetResourcePriority( DXGI_DDI_ARG_SETRESOURCEPRIORITY *SetResourcePriority )
{
   LOG_ENTRYPOINT();

   if (!SetResourcePriority)
      return E_INVALIDARG;

   Device *device = CastDevice(SetResourcePriority->hDevice);
   Resource *resource = CastResource(SetResourcePriority->hResource);
   if (!device || !resource ||
       !device->device.KTCallbacks.pfnSetPriorityCb)
      return E_INVALIDARG;

   D3DKMT_HANDLE allocation =
      dxgi_get_d3dkmt_render_allocation(device, resource);
   if (!allocation)
      return E_FAIL;

   D3DDDICB_SETPRIORITY priority = {};
   priority.NumAllocations = 1;
   priority.HandleList = &allocation;
   priority.pPriorities = &SetResourcePriority->Priority;

   return device->device.KTCallbacks.pfnSetPriorityCb(
      device->device.hRTDevice, &priority);
}


/*
 * ----------------------------------------------------------------------
 *
 * _QueryResourceResidency --
 *
 * ----------------------------------------------------------------------
 */

HRESULT APIENTRY
_QueryResourceResidency( DXGI_DDI_ARG_QUERYRESOURCERESIDENCY *QueryResourceResidency )
{
   LOG_ENTRYPOINT();

   if (!QueryResourceResidency)
      return E_INVALIDARG;

   Device *device = CastDevice(QueryResourceResidency->hDevice);
   if (!device || !device->device.KTCallbacks.pfnQueryResidencyCb ||
       (QueryResourceResidency->Resources &&
        (!QueryResourceResidency->pResources ||
         !QueryResourceResidency->pStatus)))
      return E_INVALIDARG;

   bool any_shared = false;
   bool any_not_resident = false;
   for (UINT i = 0; i < QueryResourceResidency->Resources; ++i) {
      Resource *resource = CastResource(QueryResourceResidency->pResources[i]);
      if (!resource)
         return E_INVALIDARG;

      D3DKMT_HANDLE allocation =
         dxgi_get_d3dkmt_render_allocation(device, resource);
      if (!allocation)
         return E_FAIL;

      D3DDDI_RESIDENCYSTATUS residency = {};
      D3DDDICB_QUERYRESIDENCY query = {};
      query.NumAllocations = 1;
      query.HandleList = &allocation;
      query.pResidencyStatus = &residency;

      HRESULT result = device->device.KTCallbacks.pfnQueryResidencyCb(
         device->device.hRTDevice, &query);
      if (FAILED(result))
         return result;

      switch (residency) {
      case D3DDDI_RESIDENCYSTATUS_RESIDENTINGPUMEMORY:
         QueryResourceResidency->pStatus[i] =
            DXGI_DDI_RESIDENCY_FULLY_RESIDENT;
         break;
      case D3DDDI_RESIDENCYSTATUS_RESIDENTINSHAREDMEMORY:
         QueryResourceResidency->pStatus[i] =
            DXGI_DDI_RESIDENCY_RESIDENT_IN_SHARED_MEMORY;
         any_shared = true;
         break;
      case D3DDDI_RESIDENCYSTATUS_NOTRESIDENT:
         QueryResourceResidency->pStatus[i] =
            DXGI_DDI_RESIDENCY_EVICTED_TO_DISK;
         any_not_resident = true;
         break;
      default:
         return E_FAIL;
      }
   }

   if (any_not_resident)
      return S_NOT_RESIDENT;
   if (any_shared)
      return S_RESIDENT_IN_SHARED_MEMORY;
   return S_OK;
}


/*
 * ----------------------------------------------------------------------
 *
 * _RotateResourceIdentities --
 *
 *    Rotate a list of resources by recreating their views with
 *    the updated rotations.
 *
 * ----------------------------------------------------------------------
 */

HRESULT APIENTRY
_RotateResourceIdentities(DXGI_DDI_ARG_ROTATE_RESOURCE_IDENTITIES *RotateResourceIdentities )
{
   LOG_ENTRYPOINT();

   Device *device = CastDevice(RotateResourceIdentities->hDevice);
   const bool trace = dxgi_trace_enabled(device);

   if (trace) {
      dxgi_trace_printf(device,
                        "d3d10umd: dxgi RotateResourceIdentities count=%u\n",
                        RotateResourceIdentities->Resources);
      for (UINT i = 0; i < RotateResourceIdentities->Resources; ++i) {
         char label[64];
         snprintf(label, sizeof(label), "Rotate before[%u]", i);
         dxgi_trace_resource(device, label,
                             CastResource(RotateResourceIdentities->pResources[i]));
      }
   }

   if (RotateResourceIdentities->Resources <= 1) {
      return S_OK;
   }
   UINT NumResources = RotateResourceIdentities->Resources;
   const DXGI_DDI_HRESOURCE *hResources = RotateResourceIdentities->pResources;

   if (dxgi_is_yttrium_screen(device)) {
      if (NumResources > DXGI_MAX_SWAP_CHAIN_BUFFERS) {
         yttrium_gdi_user_logf(
            "yttrium: ERROR: DXGI runtime-handle rotation rejected "
            "owner=d3d10umd-dxgi component=RotateResourceIdentities "
            "reason=resource-count-exceeds-DXGI-limit action=abort "
            "count=%u limit=%u\n",
            NumResources, DXGI_MAX_SWAP_CHAIN_BUFFERS);
         return E_INVALIDARG;
      }

      struct pipe_resource *resources[DXGI_MAX_SWAP_CHAIN_BUFFERS];

      for (UINT i = 0; i < NumResources; ++i)
         resources[i] = CastPipeResource(hResources[i]);

      const bool handles_rotated =
         yttrium_gdi_resource_rotate_runtime_handles(resources, NumResources);
      if (!handles_rotated)
         return E_FAIL;
   }

   bool framebuffer_rotated = false;
   for (UINT binding = 0; binding < device->fb.nr_cbufs; ++binding) {
      struct pipe_resource **texture = &device->fb.cbufs[binding].texture;
      for (UINT i = 0; i < NumResources; ++i) {
         if (*texture != CastPipeResource(hResources[i]))
            continue;

         pipe_resource_reference(
            texture, CastPipeResource(hResources[(i + 1) % NumResources]));
         framebuffer_rotated = true;
         break;
      }
   }

   if (device->fb.zsbuf.texture) {
      for (UINT i = 0; i < NumResources; ++i) {
         if (device->fb.zsbuf.texture != CastPipeResource(hResources[i]))
            continue;

         pipe_resource_reference(
            &device->fb.zsbuf.texture,
            CastPipeResource(hResources[(i + 1) % NumResources]));
         framebuffer_rotated = true;
         break;
      }
   }

   struct pipe_resource *firstResource = CastPipeResource(hResources[0]);

   for (UINT i = 0; i < (NumResources - 1); ++i) {
      Resource* resource = CastResource(hResources[i]);
      resource->resource = CastPipeResource(hResources[i + 1]);
   }

   Resource *lastResource = CastResource(hResources[NumResources - 1]);
   lastResource->resource = firstResource;

   if (framebuffer_rotated)
      device->pipe->set_framebuffer_state(device->pipe, &device->fb);

   if (dxgi_is_yttrium_screen(device)) {
      for (UINT i = 0; i < NumResources; ++i) {
         dxgi_sync_yttrium_primary_identity(device,
                                            CastResource(hResources[i]));
      }
   }

   device->shader_resource_views_dirty = true;

   if (trace) {
      for (UINT i = 0; i < RotateResourceIdentities->Resources; ++i) {
         char label[64];
         snprintf(label, sizeof(label), "Rotate after[%u]", i);
         dxgi_trace_resource(device, label,
                             CastResource(RotateResourceIdentities->pResources[i]));
      }
   }

   return S_OK;
}


/*
 * ----------------------------------------------------------------------
 *
 * _Blt --
 *
 *    Do a blt between two subresources. Apply MSAA resolve, format
 *    conversion and stretching.
 *
 * ----------------------------------------------------------------------
 */

struct dxgi_blt_rect
{
   UINT left;
   UINT top;
   UINT right;
   UINT bottom;
};

static bool
dxgi_blt_subresource(struct pipe_resource *resource, UINT subresource,
                     unsigned *level, unsigned *layer,
                     unsigned *width, unsigned *height)
{
   if (!resource || !level || !layer || !width || !height ||
       (resource->target != PIPE_TEXTURE_2D &&
        resource->target != PIPE_TEXTURE_2D_ARRAY))
      return false;

   const unsigned levels = resource->last_level + 1;
   *level = subresource % levels;
   *layer = subresource / levels;
   if (*layer >= resource->array_size)
      return false;

   *width = u_minify(resource->width0, *level);
   *height = u_minify(resource->height0, *level);
   return true;
}

static bool
dxgi_blt_rect_valid(const struct dxgi_blt_rect *rect,
                    unsigned width, unsigned height)
{
   return rect && rect->left < rect->right && rect->top < rect->bottom &&
          rect->right <= width && rect->bottom <= height &&
          rect->right <= INT_MAX && rect->bottom <= INT_MAX;
}

static HRESULT
dxgi_blt(Device *device, Resource *dst, UINT dst_subresource,
         const struct dxgi_blt_rect *dst_rect, Resource *src,
         UINT src_subresource, const struct dxgi_blt_rect *requested_src_rect,
         DXGI_DDI_ARG_BLT_FLAGS flags, DXGI_DDI_MODE_ROTATION rotate)
{
   if (!device || !device->pipe || !dst || !src || !dst->resource ||
       !src->resource || flags.Reserved)
      return E_INVALIDARG;

   struct pipe_resource *dst_resource = dst->resource;
   struct pipe_resource *src_resource = src->resource;
   if (!device->pipe->blit ||
       (dst_resource->target != PIPE_TEXTURE_2D &&
        dst_resource->target != PIPE_TEXTURE_2D_ARRAY) ||
       (src_resource->target != PIPE_TEXTURE_2D &&
        src_resource->target != PIPE_TEXTURE_2D_ARRAY))
      return DXGI_DDI_ERR_UNSUPPORTED;

   unsigned dst_level, dst_layer, dst_width, dst_height;
   unsigned src_level, src_layer, src_width, src_height;
   if (!dxgi_blt_subresource(dst_resource, dst_subresource,
                             &dst_level, &dst_layer,
                             &dst_width, &dst_height) ||
       !dxgi_blt_subresource(src_resource, src_subresource,
                             &src_level, &src_layer,
                             &src_width, &src_height))
      return E_INVALIDARG;

   struct dxgi_blt_rect full_src_rect = {};
   if (!requested_src_rect) {
      full_src_rect.right = src_width;
      full_src_rect.bottom = src_height;
      requested_src_rect = &full_src_rect;
   }
   if (!dxgi_blt_rect_valid(dst_rect, dst_width, dst_height) ||
       !dxgi_blt_rect_valid(requested_src_rect, src_width, src_height))
      return E_INVALIDARG;

   const UINT copy_width = requested_src_rect->right - requested_src_rect->left;
   const UINT copy_height = requested_src_rect->bottom - requested_src_rect->top;
   const UINT dst_copy_width = dst_rect->right - dst_rect->left;
   const UINT dst_copy_height = dst_rect->bottom - dst_rect->top;
   if ((!flags.Stretch &&
        (copy_width != dst_copy_width || copy_height != dst_copy_height)) ||
       (!flags.Convert && src_resource->format != dst_resource->format))
      return E_INVALIDARG;

   if ((flags.Resolve &&
        (src_resource->nr_samples <= 1 || dst_resource->nr_samples > 1)) ||
       (!flags.Resolve &&
        src_resource->nr_samples != dst_resource->nr_samples))
      return DXGI_DDI_ERR_UNSUPPORTED;

   struct pipe_blit_info info = {};
   info.dst.resource = dst_resource;
   info.dst.level = dst_level;
   info.dst.format = dst_resource->format;
   info.dst.box.x = (int)dst_rect->left;
   info.dst.box.y = (int)dst_rect->top;
   info.dst.box.z = dst_layer;
   info.dst.box.width = (int)dst_copy_width;
   info.dst.box.height = (int)dst_copy_height;
   info.dst.box.depth = 1;
   info.src.resource = src_resource;
   info.src.level = src_level;
   info.src.format = src_resource->format;
   info.src.box.x = (int)requested_src_rect->left;
   info.src.box.y = (int)requested_src_rect->top;
   info.src.box.z = src_layer;
   info.src.box.width = (int)copy_width;
   info.src.box.height = (int)copy_height;
   info.src.box.depth = 1;

   switch (rotate) {
   case DXGI_DDI_MODE_ROTATION_UNSPECIFIED:
   case DXGI_DDI_MODE_ROTATION_IDENTITY:
      break;
   case DXGI_DDI_MODE_ROTATION_ROTATE180:
      info.src.box.x = (int)requested_src_rect->right;
      info.src.box.y = (int)requested_src_rect->bottom;
      info.src.box.width = -(int)copy_width;
      info.src.box.height = -(int)copy_height;
      break;
   case DXGI_DDI_MODE_ROTATION_ROTATE90:
   case DXGI_DDI_MODE_ROTATION_ROTATE270:
      return DXGI_DDI_ERR_UNSUPPORTED;
   default:
      return E_INVALIDARG;
   }

   info.mask = util_format_get_mask(dst_resource->format) &
               util_format_get_mask(src_resource->format) & PIPE_MASK_RGBA;
   if (!info.mask)
      return DXGI_DDI_ERR_UNSUPPORTED;
   info.filter = flags.Stretch ? PIPE_TEX_FILTER_LINEAR :
                                 PIPE_TEX_FILTER_NEAREST;

   dxgi_sync_yttrium_primary_identity(device, dst);
   device->pipe->blit(device->pipe, &info);
   if (flags.Present)
      dxgi_flush_frontbuffer(device, dst_resource, dst_level, dst_layer, NULL);

   return S_OK;
}

HRESULT APIENTRY
_Blt(DXGI_DDI_ARG_BLT *Blt)
{
   LOG_ENTRYPOINT();

   if (!Blt)
      return E_INVALIDARG;

   Device *device = CastDevice(Blt->hDevice);
   Resource *dst = CastResource(Blt->hDstResource);
   Resource *src = CastResource(Blt->hSrcResource);
   const bool trace = dxgi_trace_enabled(device);

   if (trace) {
      dxgi_trace_printf(device,
                        "d3d10umd: dxgi Blt dst=%p dst_sub=%u rect=%u,%u-%u,%u src=%p src_sub=%u flags=0x%x present=%u resolve=%u convert=%u stretch=%u rotate=%u\n",
                        (void *)Blt->hDstResource,
                        Blt->DstSubresource,
                        Blt->DstLeft,
                        Blt->DstTop,
                        Blt->DstRight,
                        Blt->DstBottom,
                        (void *)Blt->hSrcResource,
                        Blt->SrcSubresource,
                        Blt->Flags.Value,
                        Blt->Flags.Present,
                        Blt->Flags.Resolve,
                        Blt->Flags.Convert,
                        Blt->Flags.Stretch,
                        Blt->Rotate);
      dxgi_trace_resource(device, "Blt dst", dst);
      dxgi_trace_resource(device, "Blt src", src);
   }

   const struct dxgi_blt_rect dst_rect = {
      Blt->DstLeft, Blt->DstTop, Blt->DstRight, Blt->DstBottom
   };
   HRESULT result = dxgi_blt(device, dst, Blt->DstSubresource, &dst_rect,
                             src, Blt->SrcSubresource, NULL,
                             Blt->Flags, Blt->Rotate);

   if (trace && SUCCEEDED(result)) {
      dxgi_trace_printf(device, "d3d10umd: dxgi Blt complete present=%u\n",
                        Blt->Flags.Present);
   }

   return result;
}

#if SUPPORT_D3D11_1
HRESULT APIENTRY
_ResolveSharedResource(DXGI_DDI_ARG_RESOLVESHAREDRESOURCE *Resolve)
{
   LOG_ENTRYPOINT();

   if (!Resolve)
      return E_INVALIDARG;

   Device *device = CastDevice(Resolve->hDevice);
   Resource *resource = CastResource(Resolve->hResource);
   if (!device || !device->pipe || !resource || !resource->resource)
      return E_INVALIDARG;

   if (!device->pipe->flush_resource || !device->pipe->flush)
      return E_NOTIMPL;

   device->pipe->flush_resource(device->pipe, resource->resource);
   yttrium_gdi_flush_labeled(device->pipe, NULL, 0,
                             "D3D10 DXGI ResolveSharedResource");
   return S_OK;
}

HRESULT APIENTRY
_Blt1(DXGI_DDI_ARG_BLT1 *Blt)
{
   LOG_ENTRYPOINT();

   if (!Blt)
      return E_INVALIDARG;

   Device *device = CastDevice(Blt->hDevice);
   Resource *dst = CastResource(Blt->hDstResource);
   Resource *src = CastResource(Blt->hSrcResource);
   const bool trace = dxgi_trace_enabled(device);

   if (trace) {
      dxgi_trace_printf(device,
                        "d3d10umd: dxgi Blt1 dst=%p dst_sub=%u rect=%u,%u-%u,%u src=%p src_sub=%u src_rect=%u,%u-%u,%u flags=0x%x present=%u resolve=%u convert=%u stretch=%u rotate=%u\n",
                        (void *)Blt->hDstResource,
                        Blt->DstSubresource,
                        Blt->DstLeft,
                        Blt->DstTop,
                        Blt->DstRight,
                        Blt->DstBottom,
                        (void *)Blt->hSrcResource,
                        Blt->SrcSubresource,
                        Blt->SrcLeft,
                        Blt->SrcTop,
                        Blt->SrcRight,
                        Blt->SrcBottom,
                        Blt->Flags.Value,
                        Blt->Flags.Present,
                        Blt->Flags.Resolve,
                        Blt->Flags.Convert,
                        Blt->Flags.Stretch,
                        Blt->Rotate);
      dxgi_trace_resource(device, "Blt1 dst", dst);
      dxgi_trace_resource(device, "Blt1 src", src);
   }

   const struct dxgi_blt_rect dst_rect = {
      Blt->DstLeft, Blt->DstTop, Blt->DstRight, Blt->DstBottom
   };
   const struct dxgi_blt_rect src_rect = {
      Blt->SrcLeft, Blt->SrcTop, Blt->SrcRight, Blt->SrcBottom
   };
   HRESULT result = dxgi_blt(device, dst, Blt->DstSubresource, &dst_rect,
                             src, Blt->SrcSubresource, &src_rect,
                             Blt->Flags, Blt->Rotate);

   if (trace && SUCCEEDED(result)) {
      dxgi_trace_printf(device, "d3d10umd: dxgi Blt1 complete present=%u\n",
                        Blt->Flags.Present);
   }

   return result;
}

HRESULT APIENTRY
_OfferResources(DXGI_DDI_ARG_OFFERRESOURCES *Offer)
{
   LOG_ENTRYPOINT();

   if (!Offer)
      return E_INVALIDARG;

   Device *device = CastDevice(Offer->hDevice);
   if (!device || (Offer->Resources && !Offer->pResources))
      return E_INVALIDARG;
   if (!Offer->Resources)
      return S_OK;
   if (!device->pipe || !device->pipe->flush_resource ||
       !device->pipe->flush ||
       !device->device.KTCallbacks.pfnOfferAllocationsCb)
      return E_NOTIMPL;

   D3DKMT_HANDLE *allocations = NULL;
   HRESULT result = dxgi_collect_d3dkmt_render_allocations(
      device, Offer->pResources, Offer->Resources, &allocations);
   if (FAILED(result))
      return result;

   for (UINT i = 0; i < Offer->Resources; ++i) {
      Resource *resource = CastResource(Offer->pResources[i]);
      device->pipe->flush_resource(device->pipe, resource->resource);
   }
   yttrium_gdi_flush_labeled(device->pipe, NULL, 0,
                             "D3D10 DXGI OfferResources");

   D3DDDICB_OFFERALLOCATIONS offer = {};
   offer.pResources = NULL;
   offer.HandleList = allocations;
   offer.NumAllocations = Offer->Resources;
   offer.Priority = Offer->Priority;
   result = device->device.KTCallbacks.pfnOfferAllocationsCb(
      device->device.hRTDevice, &offer);
   free(allocations);
   return result;
}

HRESULT APIENTRY
_ReclaimResources(DXGI_DDI_ARG_RECLAIMRESOURCES *Reclaim)
{
   LOG_ENTRYPOINT();

   if (!Reclaim)
      return E_INVALIDARG;

   Device *device = CastDevice(Reclaim->hDevice);
   if (!device || (Reclaim->Resources && !Reclaim->pResources))
      return E_INVALIDARG;
   if (!Reclaim->Resources)
      return S_OK;
   if (!device->device.KTCallbacks.pfnReclaimAllocationsCb)
      return E_NOTIMPL;

   D3DKMT_HANDLE *allocations = NULL;
   HRESULT result = dxgi_collect_d3dkmt_render_allocations(
      device, Reclaim->pResources, Reclaim->Resources, &allocations);
   if (FAILED(result))
      return result;

   D3DDDICB_RECLAIMALLOCATIONS reclaim = {};
   reclaim.pResources = NULL;
   reclaim.HandleList = allocations;
   reclaim.pDiscarded = Reclaim->pDiscarded;
   reclaim.NumAllocations = Reclaim->Resources;
   result = device->device.KTCallbacks.pfnReclaimAllocationsCb(
      device->device.hRTDevice, &reclaim);
   free(allocations);
   return result;
}

HRESULT APIENTRY
_GetMultiplaneOverlayCaps(DXGI_DDI_ARG_GETMULTIPLANEOVERLAYCAPS *Caps)
{
   LOG_ENTRYPOINT();

   if (!Caps)
      return E_INVALIDARG;

   memset(&Caps->MultiplaneOverlayCaps, 0, sizeof(Caps->MultiplaneOverlayCaps));
   return S_OK;
}

HRESULT APIENTRY
_GetMultiplaneOverlayGroupCaps(DXGI_DDI_ARG_GETMULTIPLANEOVERLAYGROUPCAPS *Caps)
{
   LOG_ENTRYPOINT();

   if (!Caps)
      return E_INVALIDARG;

   memset(&Caps->MultiplaneOverlayGroupCaps, 0, sizeof(Caps->MultiplaneOverlayGroupCaps));
   return S_OK;
}

HRESULT APIENTRY
_PresentMultiplaneOverlay(DXGI_DDI_ARG_PRESENTMULTIPLANEOVERLAY *Present)
{
   LOG_ENTRYPOINT();

   return E_NOTIMPL;
}

HRESULT APIENTRY
_Present1(DXGI_DDI_ARG_PRESENT1 *Present)
{
   LOG_ENTRYPOINT();

   if (!Present || !Present->phSurfacesToPresent ||
       !Present->SurfacesToPresent) {
      return E_INVALIDARG;
   }

   DXGI_DDI_ARG_PRESENT legacy = {};
   legacy.hDevice = Present->hDevice;
   legacy.hSurfaceToPresent = Present->phSurfacesToPresent[0].hSurface;
   legacy.SrcSubResourceIndex =
      Present->phSurfacesToPresent[0].SubResourceIndex;
   legacy.hDstResource = Present->hDstResource;
   legacy.DstSubResourceIndex = Present->DstSubResourceIndex;
   legacy.pDXGIContext = Present->pDXGIContext;
   legacy.Flags = Present->Flags;
   legacy.FlipInterval = Present->FlipInterval;

   return _Present(&legacy);
}

HRESULT APIENTRY
_CheckPresentDurationSupport(DXGI_DDI_ARG_CHECKPRESENTDURATIONSUPPORT *Support)
{
   LOG_ENTRYPOINT();

   if (!Support)
      return E_INVALIDARG;

   Support->ClosestSmallerDuration = 0;
   Support->ClosestLargerDuration = 0;
   return S_OK;
}

HRESULT APIENTRY
_DxgiReserved(void *Data)
{
   LOG_ENTRYPOINT();

   return E_NOTIMPL;
}
#endif
