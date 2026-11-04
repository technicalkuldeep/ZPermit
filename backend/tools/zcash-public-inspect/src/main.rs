//! Public data decoder only. No wallet, networking, keys, or signing code.
use serde_json::{Value, json};
use std::io::{self, Read};
use zcash_address::unified::{self, Container, Encoding, Receiver};
use zcash_primitives::transaction::{Transaction, TxVersion};
use zcash_protocol::consensus::{BranchId, NetworkType};

fn inspect(v: Value) -> Result<Value, ()> {
    match v["kind"].as_str().ok_or(())? {
        "address" => {
            let address = v["address"].as_str().ok_or(())?;
            if !address.starts_with("utest1") || address.len() > 1024 {
                return Err(());
            }
            let (network, _revision, ua) = unified::Address::decode(address).map_err(|_| ())?;
            if network != NetworkType::Test {
                return Err(());
            }
            if !ua.items().iter().any(|r| matches!(r, Receiver::Orchard(_))) {
                return Err(());
            }
            Ok(
                json!({"network":"test", "valid":true, "orchard_receiver":true,
                      "validation":"zcash_address_0.14.0"}),
            )
        }
        "transaction" => {
            let raw = hex::decode(v["raw_hex"].as_str().ok_or(())?).map_err(|_| ())?;
            let mut cursor = &raw[..];
            let tx = Transaction::read(&mut cursor, BranchId::Nu7).map_err(|_| ())?;
            if !cursor.is_empty()
                || tx.version() != TxVersion::V6
                || tx.consensus_branch_id() != BranchId::Nu7
            {
                return Err(());
            }
            let bundle = tx.ironwood_bundle().ok_or(())?;
            let transparent_inputs = tx.transparent_bundle().map_or(0, |b| b.vin.len());
            let transparent_outputs = tx.transparent_bundle().map_or(0, |b| b.vout.len());
            let single_pool = tx.sapling_bundle().is_none()
                && tx.orchard_bundle().is_none()
                && tx.sprout_bundle().is_none();
            Ok(
                json!({"txid":tx.txid().to_string(), "nu7_branch":"77190ad9",
                      "version":6, "pool":"ironwood", "ironwood_actions":bundle.actions().len(),
                      "transparent_inputs":transparent_inputs, "transparent_outputs":transparent_outputs,
                      "single_shielded_pool":single_pool}),
            )
        }
        _ => Err(()),
    }
}

fn main() {
    let mut input = String::new();
    let result = io::stdin()
        .take(4_100_000)
        .read_to_string(&mut input)
        .map_err(|_| ())
        .and_then(|_| serde_json::from_str(&input).map_err(|_| ()))
        .and_then(inspect);
    match result {
        Ok(value) => println!("{value}"),
        Err(_) => {
            eprintln!("public_data_invalid");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use zcash_address::unified::Revision;

    #[test]
    fn official_testnet_encoding_and_checksum() {
        // Synthetic public receiver fixture only: not a funded/user wallet address.
        let ua = unified::Address::try_from_items(
            Revision::R0,
            vec![unified::Uitem::Data(Receiver::Orchard([7; 43]))],
        )
        .unwrap();
        let address = ua.encode(&NetworkType::Test);
        assert_eq!(
            inspect(json!({"kind":"address","address":address})).unwrap()["valid"],
            true
        );
        let mut corrupted = address;
        let last = corrupted.pop().unwrap();
        corrupted.push(if last == 'q' { 'p' } else { 'q' });
        assert!(inspect(json!({"kind":"address","address":corrupted})).is_err());
    }

    #[test]
    fn reject_mainnet_and_truncated_transaction() {
        let ua = unified::Address::try_from_items(
            Revision::R0,
            vec![unified::Uitem::Data(Receiver::Orchard([7; 43]))],
        )
        .unwrap();
        assert!(
            inspect(json!({"kind":"address","address":ua.encode(&NetworkType::Main)})).is_err()
        );
        assert!(inspect(json!({"kind":"transaction","raw_hex":"00"})).is_err());
    }
}
