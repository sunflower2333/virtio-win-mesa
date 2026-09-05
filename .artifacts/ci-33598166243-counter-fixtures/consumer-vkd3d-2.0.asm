cs_5_0
dcl_globalFlags refactoringAllowed
dcl_uav_structured_opc u0, 4
dcl_uav_typed_buffer (uint,uint,uint,uint) u1
dcl_input vThreadID.x
dcl_temps 1
dcl_thread_group 2, 1, 1
imm_atomic_consume r0.x, u0
ld_structured_indexable(structured_buffer, stride=4)(mixed,mixed,mixed,mixed) r0.x, r0.x, l(0), u0.x
store_uav_typed u1.xyzw, vThreadID.x, r0.x
ret
