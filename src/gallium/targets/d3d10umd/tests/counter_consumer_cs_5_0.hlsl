RWStructuredBuffer<uint> values : register(u0);
RWBuffer<uint> markers : register(u1);

[numthreads(2, 1, 1)]
void
main(uint3 dispatch_id : SV_DispatchThreadID)
{
   uint index = values.DecrementCounter();
   markers[dispatch_id.x] = values[index];
}
