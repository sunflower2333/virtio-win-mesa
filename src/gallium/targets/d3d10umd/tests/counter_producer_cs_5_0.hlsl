RWStructuredBuffer<uint> values : register(u0);
RWBuffer<uint> markers : register(u1);

[numthreads(4, 1, 1)]
void
main(uint3 dispatch_id : SV_DispatchThreadID)
{
   uint index = values.IncrementCounter();
   values[index] = 98u + index;
   markers[dispatch_id.x] = index;
}
