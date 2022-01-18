{
  description = "A very basic flake";

  inputs = {
    nixpkgs.url      = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url  = "github:numtide/flake-utils";
    poetry2nix.url   = "github:nix-community/poetry2nix";
  };
  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
  flake-utils.lib.eachDefaultSystem (system:
    let
      overlays = [ poetry2nix.overlay ];
      pkgs = import nixpkgs {
        inherit system overlays;
      };
    in
    {
      packages.payfit_slack_bot = pkgs.poetry2nix.mkPoetryApplication {
        projectDir = ./.;
      };
      defaultPackage = self.packages.${system}.payfit_slack_bot;
    });
}
