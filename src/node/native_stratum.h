// Private-regtest experiment, MIT license.
#ifndef BITCOIN_NODE_NATIVE_STRATUM_H
#define BITCOIN_NODE_NATIVE_STRATUM_H
class CRPCTable;
void RegisterNativeStratumRPC(CRPCTable& table);
void StopNativeStratum();
#endif
