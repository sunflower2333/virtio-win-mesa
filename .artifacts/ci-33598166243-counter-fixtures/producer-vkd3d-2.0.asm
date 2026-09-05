cs_5_0
dcl_globalFlags refactoringAllowed
dcl_uav_structured_opc u0, 4
dcl_uav_typed_buffer (uint,uint,uint,uint) u1
dcl_input vThreadID.x
dcl_temps 1
dcl_thread_group 4, 1, 1
imm_atomic_alloc r0.x, u0
iadd r0.y, r0.x, l(98)
store_structured u0.x, r0.x, l(0), r0.y
store_uav_typed u1.xyzw, vThreadID.x, r0.x
ret
